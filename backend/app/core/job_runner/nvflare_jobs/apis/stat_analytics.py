import logging
import os
import pickle
import math
from .utils import pre_count, local_pre_mean, local_post_mean, local_pre_stdev, local_post_stdev, local_pre_chi2, local_post_chi2, local_pre_kaplan_meier, local_post_kaplan_meier, logrank_terms_from_aggregated_N_d, kaplan_meier_confidence_interval, local_pre_t_test, local_post_t_test, local_pre_get_biomarker_records, local_pre_biomarker_score_computation, local_pre_logistic_regression_with_global_zscore, local_post_meta_analysis, censor_aware_er_labels, extract_time_event_arrays
from .utils import ENC_BIOMARKER_SCORE_FAMILY, ENC_BIOMARKER_RISK_GROUP_FAMILY
from .warn_exception import WarnException


# Threshold below which both ``|mean|`` and ``stdev`` from the reference (plaintext) mean-stdev computation indicate the input signal is dominated
# by CKKS noise. The reference path uses this to emit ``status='WARN'`` so downstream consumers (and tests) know the corresponding encrypted result
# will be unreliable. 
_LOW_SNR_THRESHOLD = 1e-5


def _attach_warning(result: dict, warning: WarnException) -> dict:
    """Add a stable, UI-safe warning payload without changing legacy fields."""
    result["status"] = "WARN"
    result["msg"] = str(warning)
    result["warning"] = warning.to_payload()
    return result


def _low_signal_warning(mean: float, stdev: float, *, encrypted: bool) -> WarnException:
    path_message = (
        "Encrypted-path mean-stdev is dominated by noise."
        if encrypted
        else "Encrypted-path mean-stdev will be dominated by noise."
    )
    return WarnException(
        (
            f"Signal below CKKS noise floor: |mean|={abs(mean):.3e}, "
            f"stdev={stdev:.3e}, threshold={_LOW_SNR_THRESHOLD:.0e}. "
            f"{path_message}"
        ),
        code="LOW_SIGNAL_TO_NOISE",
        details={
            "mean": mean,
            "stdev": stdev,
            "threshold": _LOW_SNR_THRESHOLD,
        },
    )


def _degenerate_lr_warning() -> WarnException:
    return WarnException(
        (
            "Local logistic regression fit was degenerate. This can occur "
            "when the cohort has too few usable records, only one outcome "
            "class, a singular design matrix, or a missing/zero score "
            "standard deviation."
        ),
        code="DEGENERATE_LOGISTIC_REGRESSION",
    )


def _time_grid_clamped_warning(requested: float, effective: float) -> WarnException:
    return WarnException(
        (
            f"Configured time_grid_max={requested:g} exceeds this datasource's "
            f"ceiling and was clipped to {effective:g} (schema "
            f"biomarker_km_time_grid_max). Patient times beyond {effective:g} "
            f"are aggregated into the last grid cell."
        ),
        code="TIME_GRID_MAX_CLIPPED",
        details={"requested": requested, "effective": effective},
    )


def _single_risk_group_warning(group: str | None = None) -> WarnException:
    return WarnException(
        "Single risk group — log-rank test not applicable",
        code="SINGLE_RISK_GROUP_NO_LOGRANK",
        details={"group": group} if group else {},
    )


def _degenerate_chi2_warning(dof: int) -> WarnException:
    return WarnException(
        (
            "Chi-squared test not applicable: after dropping categories with no records, "
            "one of the two variables has fewer than two categories left "
            f"(degrees of freedom = {dof}). This happens when a filter pins that variable to a "
            "single value. No p-value is defined."
        ),
        code="DEGENERATE_CHI2_NO_TEST",
        details={"dof": dof},
    )


def _invalid_chi2_warning(chi2: float) -> WarnException:
    """A chi2 statistic sums squares over positive denominators, so it cannot be negative.

    A negative value means the aggregate is not a statistic at all -- on the encrypted path the
    usual cause is the per-cell shares of zero failing to cancel, which leaves a residual on the
    order of the additive-mask magnitude.
    """
    return WarnException(
        (
            f"Chi-squared statistic is negative ({chi2:.6g}), which is mathematically impossible. "
            "The aggregate is unreliable and no p-value is reported."
        ),
        code="INVALID_CHI2_NEGATIVE",
        details={"chi2": chi2},
    )


def _chi2_result(chi2: float, p_value: float | None, dof: int) -> dict:
    """Assemble the chi2 result, flagging the two ways the test can come back unusable.

    Shared by the clear and encrypted postprocess so both surface the same payload.
    """
    result = {"chi2": chi2, "p_value": p_value}
    # Degeneracy is checked first: a dof <= 0 test is structurally undefined, and on the
    # encrypted path its statistic is exactly zero in the clear (every real cell has
    # observed == expected) so CKKS noise routinely makes it come back slightly negative.
    # Letting the chi2 < 0 branch win there would report a spurious "impossible statistic"
    # instead of the real, actionable reason -- a variable pinned to a single category.
    if dof <= 0:
        result["p_value"] = None
        warning = _degenerate_chi2_warning(dof)
    elif chi2 < 0:
        result["p_value"] = None
        warning = _invalid_chi2_warning(chi2)
    else:
        return result
    logging.getLogger(__name__).warning("%s", warning)
    return _attach_warning(result, warning)


class StatAnalyticsManager:
    def __init__(
        self,
        computation_type: str = None,
        data_column_id: str = None,
        category_column_1_id: str = None,
        category_column_2_id: str = None,
        group_column_id: str = None,
        time_column_id: str = None,
        censoring_column_id: str = None,
        column_1_categories: list = [],
        column_2_categories: list = [],
        group_categories: list = [],
        time_grid_min: int = None,
        time_grid_step: int = None,
        time_grid_max: int = None,
        scale_factor = None,
        global_min = None,
        global_max = None,
        global_count = None,
        std_type: str = "sample",
        stat_data_path: str = None,     # TODO: Replace with column_values once data is passed as a list of values.
        filters = None
    ):
        '''Initializes the StatAnalyticsManager component.

        Args:
            computation_type (str): The type of computation to perform. Possible values: ["mean", "stdev", "mean-stdev", "chi2", "kaplan-meier", "frequencies", "clear_filter"] (mandatory)
            data_column_id (str): Name of the column to perform the computation on. Column type should be numeric. (mandatory: mean)
            category_column_1_id (str): Name of the category column to use for first category. Column type should be categorical. (mandatory: chi2)
            category_column_2_id (str): Name of the category column to use for second category. Column type should be categorical. (mandatory: chi2)
            group_column_id (str): Name of the column that indicates to which group a sample belongs to. Column type should be categorical. (mandatory: kaplan-meier)
            time_column_id (str): Name of the column of the event times. Column type should be numeric. (mandatory: kaplan-meier)
            censoring_column_id (str): Name of the column specifying whether death occurred (value of 1) or subject left the trial (value of 0). Column type should be categorical. (mandatory: kaplan-meier)
            column_1_categories (list): List of all possible categories in category_column_1_id. (mandatory: chi2)
            column_2_categories (list): List of all possible categories in category_column_2_id. (mandatory: chi2)
            group_categories (list): List of all possible groups in group_column_id. (mandatory: kaplan-meier)
            time_grid_min (int): Grid minimum value (first point in grid). (mandatory: kaplan-meier)
            time_grid_step (int): Distance between grid points (step). (mandatory: kaplan-meier)
            time_grid_max (int): Grid maximum value. (mandatory: kaplan-meier)
            scale_factor (float): A scaling factor to apply to the data before processing; used for data normalization
            global_min (float): Min value across all data; used for data normalization.
            global_max (float): Max value across all data; used for data normalization.
            global_count (float): Global count across all data; used for data normalization.
            std_type (str): Type of standard deviation to compute. Possible values: ["population", "sample"]
            stat_data_path (str): Path to the statistical data file for analytics.
            filters: Tuple of filter conditions to apply.
        '''
        self.computation_type = computation_type
        self.stat_data_path = stat_data_path
        self.filters = filters

        self.data_column_id = data_column_id
        self.category_column_1_id = category_column_1_id
        self.category_column_2_id = category_column_2_id
        self.group_column_id = group_column_id
        self.time_column_id = time_column_id
        self.censoring_column_id = censoring_column_id

        self.time_grid_min = time_grid_min
        self.time_grid_step = time_grid_step
        self.time_grid_max = time_grid_max
        self.time_grid_max_requested = None
        self.scale_factor = scale_factor
        self.global_min = global_min
        self.global_max = global_max
        self.global_count = global_count
        self.std_type = std_type

        self.column_1_categories = column_1_categories
        self.column_2_categories = column_2_categories
        self.group_categories = group_categories

        self.is_biomarker_discovery = None
        self.cancer_type = None
        self.biomarker_covariates = None
        self.coeffs = None
        self.cutoff_value = None
        self.risk_scores = None
        self.risk_scores_scale_factor = None
        self.model_key = None
        self.ci_type = None
        self.horizon_threshold = None  # biomarker_lr_fit: y = (time > horizon_threshold)
        self.cached_lr_field = None    # set on the mean workflow when sourcing from the LR cache
        self.over_cached_scores = False  # set on the mean-stdev workflow when sourcing from cached_risk_scores
        self.from_cached_score = False   # set on a kaplan-meier discovery workflow to reuse cached_risk_scores for grouping

        # Per-client caches filled by the biomarker-LR workflow chain,
        # consumed by subsequent workflows. Intentionally NOT cleared by
        # ``reset_computation_props`` so they survive workflow boundaries.
        #
        # - ``cached_risk_scores`` is filled by ``biomarker_score_computation``.
        # - ``cached_scores_mean``/``cached_scores_std`` are filled by the
        #   subsequent ``mean-stdev`` workflow run with ``over_cached_scores``;
        #   they carry the global (μ, σ) back to each client.
        # - ``cached_lr_fit`` is filled by ``biomarker_lr_fit``, which
        #   z-normalizes the cached scores with (μ, σ) and fits the local logit.
        self.cached_risk_scores = None
        self.cached_scores_model_key = None  # model_key the cached_risk_scores were computed for (reuse-guard for KM)
        self.cached_scores_mean = None
        self.cached_scores_std = None
        self.cached_lr_fit = None  # {"status": "OK", "beta0", "beta1", ...} / {"status": "FAIL", "fail_reason", ...} / None if never attempted
        # Per-patient count set by the split score path's preprocess (the score-cache
        # producer / LCS postprocess) so the round-2 fusion can trim the decrypted,
        # batched slot vector back to a per-patient list.
        self._enc_score_n_patients = None
        # Transient status of the fused biomarker_lr_fit step inside the
        # encrypted meta-analysis preprocess. Set by ``_run_fused_biomarker_lr_fit``
        # to the same shape the standalone ``biomarker_lr_fit`` postprocess
        # would emit ({"status": "OK"} or {"status": "WARN", "msg": ...}).
        # The executor writes it to a per-client lr_fit status file so the
        # sweep tests can detect a degenerate encrypted-side fit even though
        # the fused step does not have a standalone workflow.
        self._fused_lr_fit_status = None

        self.observed_result = {}     # Storing reference result for verification
        self.epsilon = 1e-3   # relative tolerance (~0.1%)
        self.abs_floor = 1e-6  # absolute floor for very small numbers

        self.custom_logger = logging.getLogger("custom.audit_log")

    def reset_computation_props(self) -> None:
        """Clear workflow/computation state before a new init load.

        Preserves ``stat_data_path``, ``filters`` (set at START_RUN / data load),
        and tolerance settings ``epsilon``, ``abs_floor``. Resets everything else
        that ``set_props_from_init_load`` may set, plus ``observed_result``.
        """
        self.computation_type = None
        self.data_column_id = None
        self.category_column_1_id = None
        self.category_column_2_id = None
        self.group_column_id = None
        self.time_column_id = None
        self.censoring_column_id = None
        self.time_grid_min = None
        self.time_grid_step = None
        self.time_grid_max = None
        self.time_grid_max_requested = None
        self.scale_factor = None
        self.global_min = None
        self.global_max = None
        self.global_count = None
        self.std_type = "sample"
        self.column_1_categories = []
        self.column_2_categories = []
        self.group_categories = []
        self.is_biomarker_discovery = None
        self.cancer_type = None
        self.biomarker_covariates = None
        self.coeffs = None
        self.cutoff_value = None
        self.risk_scores = None
        self.risk_scores_scale_factor = None
        self.model_key = None
        self.ci_type = None
        self.horizon_threshold = None
        self.cached_lr_field = None
        self.over_cached_scores = False
        self.from_cached_score = False
        self._fused_lr_fit_status = None
        self.observed_result = {}

    @staticmethod
    def _is_nvflare_simulator() -> bool:
        v = os.getenv("FL_IS_SIMULATOR", "").strip().lower()
        return v in ("1", "true", "yes", "on")

    def _apply_filter_in_simulation_mode(self, args: dict) -> None:
        """When no UI filters.json is present, mirror deployment by cohorting on workload_args cancer_type."""
        if not self._is_nvflare_simulator():
            return
        if self.filters:
            return
        ct = args.get("cancer_type")
        if ct is None:
            return
        if isinstance(ct, str) and not ct.strip():
            return
        value = ct.strip() if isinstance(ct, str) else ct
        self.filters = [
            {
                "filter_type": "PATIENT_DATA",
                "column_name": "cancer_type",
                "operator": "=",
                "value": value,
            }
        ]

    def set_props_from_init_load(self, workload_args: dict, generated_args: dict) -> dict:
        '''Sets relevant properties from the initial load arguments.
        Args:
            workload_args (dict): The workload arguments provided during initialization.
            generated_args (dict): The generated arguments provided during initialization.
        '''
        metadata={}
        args = {**workload_args, **generated_args}
        self._apply_filter_in_simulation_mode(args)
        self.computation_type = args['computation_type']
        if self.computation_type == "mean" or self.computation_type == "stdev" or self.computation_type == "mean-stdev":
            if self.computation_type == "mean" and args.get("cached_lr_field") is not None:
                self.cached_lr_field = args["cached_lr_field"]
                self.global_min = None
                self.global_max = None
                self.global_count = None
                metadata["global_min"] = None
                metadata["global_max"] = None
                metadata["global_count"] = None
                return metadata
            if self.computation_type == "mean-stdev" and args.get("over_cached_scores") is True:
                self.over_cached_scores = True
                self.global_min = None
                self.global_max = None
                self.global_count = None
                metadata["global_min"] = None
                metadata["global_max"] = None
                metadata["global_count"] = None
                self.std_type = args.get('std_type', 'sample')
                metadata["std_type"] = self.std_type
                # The shared standardization is defined over the ER-labeled rows only
                # (censor-aware, reference section F.2), so the share needs the training
                # ER horizon and the time/event columns. ``horizon_threshold`` is injected
                # by the server persistor from the model_upload cutoff artifact (or
                # pre-injected by the stager on the encrypted chain), exactly like the
                # meta-analysis / biomarker_lr_fit workflows.
                if args.get("horizon_threshold") is not None:
                    self.time_column_id = args.get("time_column_id")
                    self.censoring_column_id = args.get("censoring_column_id")
                    self.horizon_threshold = float(args["horizon_threshold"])
                # Optional fused biomarker_score_computation: when ``coeffs`` is provided, the mean-stdev preprocess will
                # compute the per-patient scores inline (instead of relying on a prior workflow_biomarker_score_computation
                # round to have populated ``cached_risk_scores``). Used by the open-access path to drop an empty round.
                if args.get("coeffs") is not None:
                    if isinstance(args["coeffs"], bytes):
                        self.coeffs = pickle.loads(args["coeffs"])
                    else:
                        self.coeffs = args["coeffs"]
                    self.cancer_type = args.get("cancer_type")
                    self.biomarker_covariates = args.get("biomarker_covariates")
                    self.model_key = args.get("model_key")
                return metadata
            self.data_column_id = args['data_column_id']
            self.global_min = args['global_min']
            self.global_max = args['global_max']
            self.global_count = args['global_count']
            metadata["global_count"] = self.global_count
            if self.computation_type == "stdev" or self.computation_type == "mean-stdev":
                self.std_type = args['std_type']
                metadata["std_type"] = self.std_type
        elif self.computation_type == "chi2":
            self.category_column_1_id = args['category_column_1_id']
            self.category_column_2_id = args['category_column_2_id']
            self.column_1_categories = args['column_1_categories']
            self.column_2_categories = args['column_2_categories']
            self.scale_factor = args['scale_factor']
            metadata={
                "len_category1": len(self.column_1_categories),
                "len_category2": len(self.column_2_categories),
                "scale_factor": self.scale_factor
                }
        elif self.computation_type == "kaplan-meier":
            self.group_column_id = args['group_column_id']
            self.time_column_id = args['time_column_id']
            self.censoring_column_id = args['censoring_column_id']
            self.group_categories = args['group_categories']
            self.time_grid_min = args['time_grid_min']
            self.time_grid_step = args['time_grid_step']
            self.time_grid_max = args['time_grid_max']
            # Present only when the server overrode a differing configured value
            # with the datasource schema's ceiling; postprocess surfaces a warning.
            self.time_grid_max_requested = args.get('time_grid_max_requested')
            self.scale_factor = args['scale_factor']
            ci_type = args.get('CI_type', None)
            self.ci_type = None if (ci_type is None or str(ci_type).lower() == "none") else ci_type
            if "is_biomarker_discovery" in args and args["is_biomarker_discovery"] == True:
                self.is_biomarker_discovery = args["is_biomarker_discovery"]
                self.cancer_type = args["cancer_type"]
                self.biomarker_covariates = args['biomarker_covariates']
                self.model_key = args.get("model_key")
                # Open-access reuse: group on the raw scores cached by a preceding
                # biomarker_score_computation instead of re-deriving them (see preprocess).
                self.from_cached_score = bool(args.get("from_cached_score", False))
                if "w_biomarker_risk_scores" in args:
                    self.risk_scores = args["w_biomarker_risk_scores"]
                if "risk_scores_scale_factor" in args:
                    self.risk_scores_scale_factor = args["risk_scores_scale_factor"]
                if self.risk_scores is None:    # If server (model owner), simply load model.
                    if isinstance(args["coeffs"], bytes):
                        self.coeffs = pickle.loads(args["coeffs"])
                    else:
                        self.coeffs = args["coeffs"]
                    self.cutoff_value = args["cutoff_value"]
            import math
            M_steps = math.ceil((self.time_grid_max - self.time_grid_min) / self.time_grid_step)
            time_grid = [self.time_grid_min + ind * self.time_grid_step for ind in range(int(M_steps))]
            if time_grid and time_grid[-1] < self.time_grid_max: # Ensure max_time is covered if not perfectly aligned
                time_grid.append(self.time_grid_max)
            metadata = {
                    "len_time_grid": len(time_grid),
                    "scale_factor": self.scale_factor,
                    "CI_type": self.ci_type
                    }
        elif self.computation_type == "t-test":
            self.data_column_id = args['data_column_id']
            self.global_min = args['global_min']
            self.global_max = args['global_max']
            self.global_count = args['global_count']
            self.category_column_1_id = args['category_column_1_id']
            self.column_1_categories = args['column_1_categories']
            metadata = {"global_count": self.global_count}
        elif self.computation_type == "meta-analysis":
            self.global_min = None
            self.global_max = None
            self.global_count = None
            metadata["global_min"] = None
            metadata["global_max"] = None
            metadata["global_count"] = None
            self.model_key = args.get("model_key")  # fused lr_fit needs it for the cox_lasso β₁ flip
            if args.get("horizon_threshold") is not None:
                self.time_column_id = args.get("time_column_id")
                self.censoring_column_id = args.get("censoring_column_id")
                self.horizon_threshold = float(args["horizon_threshold"])
        elif self.computation_type in ENC_BIOMARKER_RISK_GROUP_FAMILY:
            # ``biomarker_enc_risk_group_postprocess`` is the split-architecture KM consumer:
            # same client-side inputs as fused discovery, but it uploads NO covariates (the
            # producer cached the packed score); the server applies the -cutoff/x rm tail to
            # the cache. Same set_props so the decrypt round + masks are identical.
            self.cancer_type = args["cancer_type"]
            self.biomarker_covariates = args['biomarker_covariates']
            metadata["model_keys"] = list(args["model_keys"])
            metadata["biomarker_models_by_key"] = args["biomarker_models_by_key"]
        elif self.computation_type in ENC_BIOMARKER_SCORE_FAMILY:
            # ``biomarker_enc_score_cache`` is the split-architecture producer: it uses the exact
            # same client-side inputs (cancer_type, covariates, model artifacts), computes the
            # neutral packed score at the server, and caches it -- no decrypt round.
            # ``biomarker_enc_score_postprocess`` is the split-architecture LCS consumer: it uploads
            # NO covariates (the producer already cached the packed score); it only preprocesses to
            # learn its own patient count/covariate order so the round-2 fusion can trim + cache the
            # descaled scores. The KM/LCS postprocess consumers read the producer's cache.
            # See UnifiedBiomarkerScorePlan.md.
            self.cancer_type = args["cancer_type"]
            self.biomarker_covariates = args['biomarker_covariates']
            self.model_key = args.get("model_key")
            metadata["model_keys"] = list(args["model_keys"])
            metadata["biomarker_models_by_key"] = args["biomarker_models_by_key"]
        elif self.computation_type == "biomarker_score_computation":
            # Open-access analogue of ``biomarker_enc_risk_group_computation`` each client locally applies the (open-access) biomarker model to
            # its own covariates and caches the per-patient scores. Nothing leaves the client. The subsequent ``mean-stdev`` workflow (run
            # with ``over_cached_scores=True``) aggregates the scores under HE to recover the global (μ, σ); the local logistic-regression fit
            # is deferred to the ``biomarker_lr_fit`` workflow that runs after.
            self.cancer_type = args["cancer_type"]
            self.biomarker_covariates = args['biomarker_covariates']
            self.model_key = args.get("model_key")
            if isinstance(args.get("coeffs"), bytes):
                self.coeffs = pickle.loads(args["coeffs"])
            else:
                self.coeffs = args.get("coeffs")
        elif self.computation_type == "biomarker_lr_fit":
            # Clear-text fit step that consumes the cached per-patient scores produced by ``biomarker_score_computation`` and the global
            # (μ, σ) of those scores recovered by the preceding ``mean-stdev`` workflow. Each client z-normalizes its own scores with the
            # global (μ, σ), builds y = (time > horizon_threshold), and fits the 2-parameter logit locally. The resulting (β₀, β₁, n) triple
            # is cached on the manager and consumed by the subsequent encrypted ``mean`` workflows.
            self.time_column_id = args['time_column_id']
            self.censoring_column_id = args['censoring_column_id']
            self.horizon_threshold = float(args['horizon_threshold'])
            self.model_key = args.get("model_key")  # cox_lasso β₁ flip in the unfused path
        return metadata


    def _km_cached_score_reuse(self):
        """Return ``(from_cached_score, cached_scores)`` for a kaplan-meier discovery workflow.

        When ``from_cached_score`` is set (open-access combined KM+LCS jobs), the KM grouping
        reuses the per-patient raw scores a preceding ``biomarker_score_computation`` cached on
        this manager, instead of re-deriving them from the on-disk model. The reuse must be for
        the SAME model: a missing or mismatched cache means the reuse chain is misconfigured, so
        we fail loud rather than silently recompute (a silent fallback would hide a broken chain,
        the "hollow validation" trap the encrypted path hit). Returns ``(False, None)`` when
        reuse is not requested, so the caller recomputes as before.
        """
        if not self.from_cached_score:
            return False, None
        if self.cached_risk_scores is None:
            raise Exception(
                "kaplan-meier from_cached_score is set but no cached risk scores are present; a "
                "biomarker_score_computation workflow must populate them before this KM workflow."
            )
        if (
            self.cached_scores_model_key is not None
            and self.model_key is not None
            and self.cached_scores_model_key != self.model_key
        ):
            raise Exception(
                f"kaplan-meier from_cached_score model mismatch: cached scores are for "
                f"'{self.cached_scores_model_key}' but this KM workflow is '{self.model_key}'."
            )
        return True, self.cached_risk_scores

    # ------------------------------------------------------------------
    # Reference Computation: No normalization, No Encryption, No Random masking
    # ------------------------------------------------------------------
    def preprocess_reference(self):
        if self.computation_type == "mean":
            if self.cached_lr_field is not None:
                return self._mean_share_from_cached_lr_fit()
            result = local_pre_mean(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, filters=self.filters)
            return result
        elif self.computation_type == "stdev":
            result = local_pre_stdev(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, filters=self.filters)
            return result
        elif self.computation_type == "mean-stdev":
            if self.over_cached_scores:
                if self.cached_risk_scores is None and self.coeffs is not None:
                    self._run_fused_biomarker_score_computation()
                return self._mean_stdev_share_from_cached_scores()
            result = local_pre_stdev(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, filters=self.filters)
            return result
        elif self.computation_type == "meta-analysis":
            if self.cached_lr_fit is None and self.horizon_threshold is not None:
                self._run_fused_biomarker_lr_fit()
            return self._meta_analysis_share_from_cached_lr_fit()
        elif self.computation_type == "chi2":
            result = local_pre_chi2(stat_data_path=self.stat_data_path,
                                        column_1=self.category_column_1_id,
                                        column_1_categories=self.column_1_categories,
                                        column_2=self.category_column_2_id,
                                        column_2_categories=self.column_2_categories,
                                        filters=self.filters
                                    )
            return result
        elif self.computation_type == "kaplan-meier":
            from_cached_score, cached_scores = self._km_cached_score_reuse()
            groups_data = local_pre_kaplan_meier(
                                        stat_data_path=self.stat_data_path,
                                        filters=self.filters,
                                        group_col=self.group_column_id,
                                        time_col=self.time_column_id,
                                        censoring_col=self.censoring_column_id,
                                        group_categories=self.group_categories,
                                        time_grid_min=self.time_grid_min,
                                        time_grid_step=self.time_grid_step,
                                        time_grid_max=self.time_grid_max,
                                        is_biomarker_discovery=self.is_biomarker_discovery,
                                        cancer_type=self.cancer_type,
                                        biomarker_covariates=self.biomarker_covariates,
                                        coeffs=self.coeffs,
                                        cutoff_value=self.cutoff_value,
                                        risk_scores=self.risk_scores,
                                        risk_scores_scale_factor=self.risk_scores_scale_factor,
                                        model_key=self.model_key,
                                        from_cached_score=from_cached_score,
                                        cached_scores=cached_scores,
                                    )
            # The clear path aggregates N and d only; zeros_N/ones_N exist for the encrypted
            # aggregator's zero-denominator guard, which has no counterpart here.
            groups_data = {g: {"N": v["N"], "d": v["d"]} for g, v in groups_data.items()}
            return groups_data
        elif self.computation_type == "t-test":
            result = local_pre_t_test(
                                        stat_data_path=self.stat_data_path,
                                        data_column_id=self.data_column_id,
                                        column_1=self.category_column_1_id,
                                        column_1_categories=self.column_1_categories,
                                        filters=self.filters
                                    )
            return result
        elif self.computation_type == "biomarker_score_computation":
            # Compute and cache per-patient scores. The LR fit is deferred to ``biomarker_lr_fit`` so it can use the global (μ, σ) recovered
            # by the intermediate ``mean-stdev`` workflow.
            scores = local_pre_biomarker_score_computation(
                stat_data_path=self.stat_data_path,
                filters=self.filters,
                cancer_type=self.cancer_type,
                biomarker_covariates=self.biomarker_covariates,
                coeffs=self.coeffs,
            )
            self.cached_risk_scores = scores
            # Record which model these scores belong to, so a downstream kaplan-meier
            # reuse (from_cached_score) can assert it is grouping on the right model.
            self.cached_scores_model_key = self.model_key
            return {}
        elif self.computation_type == "biomarker_lr_fit":
            # Fit the local 2-parameter logit on the cached scores after z-normalizing with the global (μ, σ) cached by the preceding
            # ``mean-stdev`` workflow. The (β₀, β₁, n) triple is cached on the manager and consumed by the subsequent encrypted ``mean``
            # workflows.
            self.cached_lr_fit = None
            scores = self.cached_risk_scores
            mu = self.cached_scores_mean
            sigma = self.cached_scores_std
            if scores is not None and len(scores) > 0 and mu is not None and sigma is not None and float(sigma) > 0.0:
                self.cached_lr_fit = local_pre_logistic_regression_with_global_zscore(
                    stat_data_path=self.stat_data_path,
                    filters=self.filters,
                    time_col=self.time_column_id,
                    censoring_col=self.censoring_column_id,
                    horizon_threshold=self.horizon_threshold,
                    risk_scores=scores,
                    score_mean=float(mu),
                    score_std=float(sigma),
                    model_key=self.model_key,
                    cancer_type=self.cancer_type,
                )
            else:
                self.cached_lr_fit = {
                    "status": "FAIL",
                    "fail_reason": "no_cached_scores" if not scores else "invalid_score_std",
                }
            return {}
        else:
            raise ValueError(f"Unsupported computation type: {self.computation_type}")

    def postprocess_reference(self, data):
        if self.computation_type == "mean":
            if self.cached_lr_field is not None:
                result = self._lr_field_post_from_aggregate(data)
            else:
                mean = local_post_mean(data['sum'], data['count'])
                result = {"mean": mean}
        elif self.computation_type == "stdev":
            stdev = local_post_stdev(data['numerator'], data['denominator'])
            result = {"stdev": stdev}
        elif self.computation_type == "meta-analysis":
            result = local_post_meta_analysis(data['sum'], data['count'], data.get('usable'))
        elif self.computation_type == "mean-stdev":
            count = float(data.get('count', 0) or 0)
            denom = float(data.get('denominator', 0) or 0)
            if count <= 0 or denom <= 0:
                # No data on this client (empty cohort / cached_risk_scores is empty). Return a graceful FAIL dict instead of dividing
                # by zero. This is reachable on the per-client local-only result path; the federated aggregate at the server still
                # runs on the union of all clients' shares.
                result = {
                    "status": "FAIL",
                    "msg": "empty cohort (count = 0); skipping mean-stdev",
                    "mean": None,
                    "stdev": None,
                }
                if self.over_cached_scores:
                    # Don't overwrite the cached μ,σ on this client; leave whatever (or None) the previous workflow set.
                    result["mean_scores"] = None
                    result["stdev_scores"] = None
            else:
                mean = local_post_mean(data['sum'], data['count'])
                stdev = local_post_stdev(data['numerator'], data['denominator'])
                if self.over_cached_scores:
                    # Persist on the manager so the next workflow on this client process (``biomarker_lr_fit``) can z-normalize the cached
                    # scores with the global (μ, σ).
                    self.cached_scores_mean = mean
                    self.cached_scores_std = stdev
                    result = {
                        "mean_scores": mean,
                        "stdev_scores": stdev,
                    }
                else:
                    result = {"mean": mean, "stdev": stdev}
                if abs(mean) < _LOW_SNR_THRESHOLD and stdev < _LOW_SNR_THRESHOLD:
                    logging.getLogger(__name__).warning(
                        "Reference mean-stdev below CKKS noise floor: "
                        "|mean|=%.3e, stdev=%.3e, threshold=%.0e. "
                        "Encrypted-path result will be unreliable.",
                        abs(mean), stdev, _LOW_SNR_THRESHOLD,
                    )
                    # Keep a recognized analytical condition in the normal
                    # result path. An unhandled exception would fail the task.
                    try:
                        raise _low_signal_warning(mean, stdev, encrypted=False)
                    except WarnException as warning:
                        _attach_warning(result, warning)
        elif self.computation_type == "chi2":
            chi2, p_value = local_post_chi2(data['numerator'], data['denominator'], data['dof'])
            result = _chi2_result(chi2, p_value, data['dof'])
        elif self.computation_type == "kaplan-meier":
            aggregated_N_groups = data["aggregated_N_groups"]
            aggregated_d_groups = data["aggregated_d_groups"]
            if 'numerator_A' in data:
                numerator_A_val = data["numerator_A"]
                denominator_A_val = data["denominator_A"]
                numerator_var_A_val = data["numerator_var_A"]
                denominator_var_A_val = data["denominator_var_A"]
                S_output, times, chi2, p_value = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups, numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val)
                result = {"S_output": S_output, "times": times, "chi2": chi2, "p_value": p_value}
            else:
                logrank_terms = logrank_terms_from_aggregated_N_d(aggregated_N_groups, aggregated_d_groups)
                if logrank_terms is not None:
                    numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val = logrank_terms
                    S_output, times, chi2, p_value = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups, numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val)
                    result = {"S_output": S_output, "times": times, "chi2": chi2, "p_value": p_value}
                else:
                    S_output, times = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups)
                    result = {"S_output": S_output, "times": times}
                    # Only one risk group was populated (all patients fell on one side
                    # of the cutoff), so there is no High-vs-Low split and the log-rank
                    # test is undefined -- chi2/p_value are omitted above. Surface this
                    # as a non-fatal warning rather than silently dropping the stat.
                    km_group = next(iter(aggregated_N_groups), None) if len(aggregated_N_groups) == 1 else None
                    logging.getLogger(__name__).warning(
                        "Kaplan-Meier: single risk group (%s) -- log-rank test not applicable.",
                        km_group,
                    )
                    try:
                        raise _single_risk_group_warning(km_group)
                    except WarnException as warning:
                        _attach_warning(result, warning)
            if self.ci_type is not None:
                result["CI"] = kaplan_meier_confidence_interval(S_output, aggregated_N_groups, aggregated_d_groups, times, self.ci_type)
            if self.model_key == "logistic_reg":    # Swap high_score and low_score because high score means low_risk in logistic regression model. Helps display correctly in the UI.
                # The CI bands are keyed by the same group names and derive from their
                # own curve's (N, d, S), so they must swap together with the curves.
                for block_name in ("S_output", "CI"):
                    block = result.get(block_name, None)
                    if block and "high_score" in block and "low_score" in block:
                        high_tmp = block["high_score"]
                        block["high_score"] = block["low_score"]
                        block["low_score"] = high_tmp
            # Surface the server-side grid override so it is never silent to the
            # job's author. Don't clobber a statistical warning if one is present.
            if self.time_grid_max_requested is not None and "warning" not in result:
                try:
                    raise _time_grid_clamped_warning(
                        float(self.time_grid_max_requested), float(self.time_grid_max)
                    )
                except WarnException as warning:
                    _attach_warning(result, warning)
        elif self.computation_type == 't-test':
            if "status" in data and data["status"] == "FAIL":
                return data["msg"]
            num_d = data['num_d']
            num_den_d = data['num_den_d']
            den_den_d = data['den_den_d']
            num_t = data['num_t']
            den_t = data['den_t']
            t_score, dof, p_value = local_post_t_test(num_d, num_den_d, den_den_d, num_t, den_t)
            result = {"t_score": t_score, "dof": dof, "p_value": p_value}
        elif self.computation_type == "biomarker_score_computation":
            # Nothing to post-process; this workflow only seeds per-client caches.
            result = {"status": "OK"}
        elif self.computation_type == "biomarker_lr_fit":
            # Same shape as biomarker_score_computation: the fit stays local and nothing is aggregated. Surface a WARN here when the local
            # fit was degenerate.
            fit = self.cached_lr_fit
            fit_failed = fit is None or fit.get("status") != "OK"
            if fit_failed:
                logging.getLogger(__name__).warning(
                    "biomarker_lr_fit: local fit degenerate "
                    "(scores=%s, mu=%s, sigma=%s, fail_reason=%s); "
                    "client will contribute zero share to meta-analysis.",
                    "missing" if self.cached_risk_scores is None else f"n={len(self.cached_risk_scores)}",
                    self.cached_scores_mean,
                    self.cached_scores_std,
                    None if fit is None else fit.get("fail_reason"),
                )
                try:
                    raise _degenerate_lr_warning()
                except WarnException as warning:
                    result = _attach_warning({}, warning)
                if fit is not None and fit.get("fail_reason"):
                    result["fail_reason"] = fit["fail_reason"]
            else:
                # Surface this site's shared-μ/σ fit (the exact meta-share input) so the
                # per-site result is externally comparable — the local/Initiator card
                # deliberately uses local μ/σ and cannot serve that purpose.
                result = {"status": "OK", "lr_fit": {k: fit[k] for k in ("beta1", "se_beta1", "n", "n_ER", "n_nonER") if k in fit}}
        else:
            raise ValueError(f"Unsupported computation type: {self.computation_type}")
        return result

    def aggregate_reference(self, accepted_data, local_analysed_data):
        '''Computing Party: performs aggregation'''
        if self.computation_type == "mean" or self.computation_type == "meta-analysis":
            if local_analysed_data is None:
                total_sum = 0
                total_count = 0
                total_usable = 0.0
            else:
                total_sum = local_analysed_data['sum']
                total_count = local_analysed_data['count']
                total_usable = float(local_analysed_data.get('usable', 0.0))

            for client_share in accepted_data.values():
                if 'sum' not in client_share or 'count' not in client_share:
                    raise KeyError(f"Missing 'sum' or 'count' in client_share.")
                total_sum += client_share['sum']
                total_count += client_share['count']
                total_usable += float(client_share.get('usable', 0.0))
            result = {"sum": total_sum, "count": total_count}
            if self.computation_type == "meta-analysis":
                # Count of sites whose fit passed the per-site gates ("mean" shares
                # don't carry it).
                result["usable"] = total_usable
            return result
        elif self.computation_type == "stdev":
            if local_analysed_data is None:
                total_sum = 0
                total_sum_sq = 0
                total_count = 0
            else:
                total_sum = local_analysed_data['sum']
                total_sum_sq = local_analysed_data['sum_sq']
                total_count = local_analysed_data['count']

            for client_share in accepted_data.values():
                if 'sum' not in client_share or 'sum_sq' not in client_share or 'count' not in client_share:
                    raise KeyError(f"Missing 'sum', 'sum_sq' or 'count' in client_share.")
                total_sum += client_share['sum']
                total_sum_sq += client_share['sum_sq']
                total_count += client_share['count']

            numerator = float(total_sum_sq) * float(total_count) - float(total_sum) * float(total_sum)
            denominator = total_count * (total_count - 1) if self.std_type == "sample" else total_count * total_count
            return {"numerator": numerator, "denominator": denominator}
        elif self.computation_type == "mean-stdev":
            if local_analysed_data is None:
                total_sum = 0
                total_sum_sq = 0
                total_count = 0
            else:
                total_sum = local_analysed_data['sum']
                total_sum_sq = local_analysed_data['sum_sq']
                total_count = local_analysed_data['count']

            for client_share in accepted_data.values():
                if 'sum' not in client_share or 'sum_sq' not in client_share or 'count' not in client_share:
                    raise KeyError(f"Missing 'sum', 'sum_sq' or 'count' in client_share.")
                total_sum += client_share['sum']
                total_sum_sq += client_share['sum_sq']
                total_count += client_share['count']

            numerator = float(total_sum_sq) * float(total_count) - float(total_sum) * float(total_sum)
            denominator = total_count * (total_count - 1) if self.std_type == "sample" else total_count * total_count
            return {"sum": total_sum, "count": total_count, "numerator": numerator, "denominator": denominator}
        elif self.computation_type == "chi2":
            # 0. Get the number of rows and columns for iteration. Since categories are consistent, both tables will have the same dimensions.
            num_rows = len(self.column_1_categories)
            num_cols = len(self.column_2_categories)
            # 0. Initialize empty 1D arrays for aggregated results.
            if local_analysed_data is None:
                cont_table = [0] * (num_rows * num_cols)
                row_marg = [0] * (num_rows * num_cols)
                col_marg = [0] * (num_rows * num_cols)
                zeros_row = [1] * (num_rows * num_cols)
                zeros_col = [1] * (num_rows * num_cols)
                N_sum = [0] * (num_rows * num_cols)
            else:
                cont_table = local_analysed_data['cont_table']
                row_marg = local_analysed_data['row_marg']
                col_marg = local_analysed_data['col_marg']
                zeros_row = local_analysed_data['zeros_row']
                zeros_col = local_analysed_data['zeros_col']
                N_sum = local_analysed_data['N_sum']

            # 1. Sum/Multiply (in a recursive way).
            # TODO: Aggregate as a balanced tree rather than a linear loop over clients.
            for client_share in accepted_data.values():
                for index in range(num_rows * num_cols):
                    cont_table[index] += client_share['cont_table'][index]
                    row_marg[index] += client_share['row_marg'][index]
                    col_marg[index] += client_share['col_marg'][index]
                    zeros_row[index] *= client_share['zeros_row'][index]
                    zeros_col[index] *= client_share['zeros_col'][index]
                    N_sum[index] += client_share['N_sum'][index]

            # 2. Compute the expected values
            expected_values = [a*b for a, b in zip(row_marg, col_marg)]

            # 3. Compute the observed values
            # observed_values = [value * N_sum for value in cont_table]
            observed_values = [a*b for a, b in zip(cont_table, N_sum)]

            # 4. Compute the numerator and denominator for chi2 statistic
            numerator = [(e - o)**2 for e, o in zip(expected_values, observed_values)]
            # denominator = [value * N_sum for value in expected_values]
            denominator = [a*b for a, b in zip(expected_values, N_sum)]

            # 5. Count the empty rows/columns. The indicators were broadcast over the flattened
            # table (each row flag repeated num_cols times, each column flag tiled num_rows
            # times) so that they line up with the outer product above; undo that before
            # counting, or every empty row counts num_cols times over.
            num_zeroes_rows = sum(zeros_row) // num_cols
            num_zeroes_cols = sum(zeros_col) // num_rows

            # 6. Compute the degrees of freedom over the categories that survive. This can be 0
            # (a dimension left with a single non-empty category), which postprocess reports as
            # an undefined test rather than a p-value.
            dof = (num_rows - 1 - num_zeroes_rows) * (num_cols - 1 - num_zeroes_cols)

            return {"numerator": numerator, "denominator": denominator, "dof": dof}
        elif self.computation_type == "kaplan-meier":
            # 0. Compute time grid
            import math
            M_steps = math.ceil((self.time_grid_max - self.time_grid_min) / self.time_grid_step)
            time_grid = [self.time_grid_min + ind * self.time_grid_step for ind in range(int(M_steps))]
            if time_grid and time_grid[-1] < self.time_grid_max: # Ensure max_time is covered if not perfectly aligned
                time_grid.append(self.time_grid_max)
            time_grid = sorted(list(set(time_grid)))

            # 0. Get set of all groups
            all_group_names = set()
            for client_share in accepted_data.values():
                all_group_names.update(client_share.keys())
            if local_analysed_data is not None: # Also include the server dataset
                all_group_names.update(local_analysed_data.keys())
            all_group_names = sorted(all_group_names)

            if self.ci_type is not None:
                # CI path: only aggregate N and d (no indicators); log-rank computed in postprocess
                if local_analysed_data is None:
                    aggregated_N_groups = {group: [0] * len(time_grid) for group in all_group_names}
                    aggregated_d_groups = {group: [0] * len(time_grid) for group in all_group_names}
                else:
                    aggregated_N_groups = {group: list(local_analysed_data[group]['N']) for group in all_group_names}
                    aggregated_d_groups = {group: list(local_analysed_data[group]['d']) for group in all_group_names}
                for client_groups_data in accepted_data.values():
                    for group_name, group_values in client_groups_data.items():
                        for i in range(len(time_grid)):
                            aggregated_N_groups[group_name][i] += group_values["N"][i]
                            aggregated_d_groups[group_name][i] += group_values["d"][i]
                return {
                    "aggregated_N_groups": aggregated_N_groups,
                    "aggregated_d_groups": aggregated_d_groups
                }

            if local_analysed_data is None:
                aggregated_N_groups = {group: [0] * len(time_grid) for group in all_group_names}
                aggregated_d_groups = {group: [0] * len(time_grid) for group in all_group_names}
            else:
                aggregated_N_groups = {group: local_analysed_data[group]['N'] for group in all_group_names}
                aggregated_d_groups = {group: local_analysed_data[group]['d'] for group in all_group_names}

            # 1: Sum across DOs. The zeros_N/ones_N indicators the encrypted aggregator needs to
            # protect its zero denominators have no counterpart here: nothing is masked, so
            # postprocess can simply skip the undefined terms.
            for client_groups_data in accepted_data.values():
                for group_name, group_values in client_groups_data.items():
                    for i in range(len(time_grid)):
                        aggregated_N_groups[group_name][i] += group_values["N"][i]
                        aggregated_d_groups[group_name][i] += group_values["d"][i]

            result = {
                "aggregated_N_groups": aggregated_N_groups,
                "aggregated_d_groups": aggregated_d_groups
            }

            unique_groups = sorted(list(all_group_names))
            if len(unique_groups) == 2:
                group_A_name, group_B_name = unique_groups[0], unique_groups[1]

                co_N_group_A = aggregated_N_groups[group_A_name]
                co_d_group_A = aggregated_d_groups[group_A_name]

                co_N_group_B = aggregated_N_groups[group_B_name]
                co_d_group_B = aggregated_d_groups[group_B_name]

                # 2. Sum co_N_group and co_d_group across all groups
                co_N = [n_a + n_b for n_a, n_b in zip(co_N_group_A, co_N_group_B)]
                co_d = [d_a + d_b for d_a, d_b in zip(co_d_group_A, co_d_group_B)]

                numerator_A = []
                denominator_A = []
                numerator_var_A = []
                denominator_var_A = []

                for i in range(len(time_grid)):
                    n_total = co_N[i]
                    n_group_A = co_N_group_A[i]
                    d_total = co_d[i]
                    d_group_A = co_d_group_A[i]

                    # 6. Compute the numerator of the expected value associated to group A
                    num_oe = (n_total * d_group_A) - (d_total * n_group_A)
                    # 7. Set the denominator of the expected value associated to group A 
                    den_oe = n_total

                    numerator_A.append(num_oe)
                    denominator_A.append(den_oe)

                    # 8. Compute the numerator of the variance in group A
                    num_var = n_group_A * (n_total - n_group_A) * d_total * (n_total - d_total)
                    # 9. Compute the denominator of the variance in group A
                    den_var = n_total * n_total * (n_total - 1)

                    numerator_var_A.append(num_var)
                    denominator_var_A.append(den_var)

                result.update({
                    "numerator_A": numerator_A,
                    "denominator_A": denominator_A,
                    "numerator_var_A": numerator_var_A,
                    "denominator_var_A": denominator_var_A
                })

            return result
        elif self.computation_type == "biomarker_score_computation":
            return {}
        elif self.computation_type == "biomarker_lr_fit":
            return {}
        elif self.computation_type == "t-test":
            import math
            # Prepare result collection data structures
            result = {}
            for cat in self.column_1_categories:
                result[cat] = {'sum_sq': 0, 'sum': 0, 'count': 0}
            if local_analysed_data is not None:
                for cat in self.column_1_categories:
                    if local_analysed_data[cat] is not None:
                        for key in local_analysed_data[cat]:
                            result[cat][key] += local_analysed_data[cat][key]

            # Aggregate
            for client_share in accepted_data.values():
                for cat in self.column_1_categories:
                    for key in client_share[cat]:
                        result[cat][key] += client_share[cat][key]

            cat0 = self.column_1_categories[0]
            cat1 = self.column_1_categories[1]

            mean={}
            var = {}
            stdev = {}
            count = {}
            temp = {}
            for cat in self.column_1_categories:
                if result[cat]['count'] <= 1:
                    return {"status": "FAIL", "msg": "Dataset doesn't have exactly 2 categories with count > 1."}
                mean[cat] = result[cat]['sum'] / result[cat]['count']
                var[cat] = (result[cat]['count']*result[cat]['sum_sq'] - result[cat]['sum']*result[cat]['sum']) / (result[cat]['count']*(result[cat]['count']-1))
                stdev[cat] = math.sqrt(var[cat])
                count[cat] = result[cat]['count']
                temp[cat] = result[cat]['count']*result[cat]['sum_sq'] - result[cat]['sum']*result[cat]['sum']

            # # T-score - standard version
            # num_t = (mean[cat0] - mean[cat1])
            # den_t = (var[cat0]/count[cat0] + var[cat1]/count[cat1])
            # t_score = num_t / math.sqrt(den_t)

            # # Degree of freedom - standard version
            # num_d = den_t**2
            # term1_den_d = (var[cat0]/count[cat0])**2 / (count[cat0]-1)
            # term2_den_d = (var[cat1]/count[cat1])**2 / (count[cat1]-1)
            # den_d = term1_den_d + term2_den_d
            # dof = num_d / den_d

            # Degree of freedom - used in encrypted workflow
            num_den_d_1 = count[cat1]**2 * (count[cat1]-1) * temp[cat0]
            num_den_d_2 = count[cat0]**2 * (count[cat0]-1) * temp[cat1]
            num_d = num_den_d_1 + num_den_d_2
            den_den_d_1 = count[cat0]-1
            den_den_d_2 = count[cat1]-1
            # dof = num_d**2/((num_den_d_1**2/den_den_d_1) + (num_den_d_2**2/den_den_d_2))

            # T-score - used in encrypted workflow
            num_t = (result[cat0]['sum']*count[cat1] - result[cat1]['sum']*count[cat0])**2 * (count[cat0] - 1)*(count[cat1] - 1)
            den_t = num_d
            # t_score = math.sqrt(num_t/den_t)
            # print(f"DEBUG: Reference t-test computation: c0 = {temp[cat0]}, c1 = {temp[cat1]}.")
            # print(f"DEBUG: Reference t-test result: num_d={num_d}, num_den_d=({num_den_d_1}, {num_den_d_2}), den_den_d=({den_den_d_1}, {den_den_d_2}), num_t={num_t}, den_t={den_t}")

            return {"num_d": num_d, "num_den_d": [num_den_d_1, num_den_d_2], "den_den_d": [den_den_d_1, den_den_d_2], "num_t": num_t, "den_t": den_t}
        else:
            raise ValueError(f"Unsupported computation type: {self.computation_type}")

    # ------------------------------------------------------------------
    # Encrypted Computation
    # ------------------------------------------------------------------
    def handle_pre_count(self, merged_args, threshold):
        self.custom_logger.info(f"Pre-processing for computation = _PRE_COUNT_UNSECURE_ or _PRE_COUNT_SECURE_")
        count = pre_count(self.stat_data_path, merged_args, threshold, self.filters)
        return {"count": count}

    def preprocess(self):
        '''Data Owner: performs local compute'''
        self.custom_logger.info(f"Pre-processing data for computation = {self.computation_type}")
        if self.computation_type == "mean":
            if self.cached_lr_field is not None:
                return self._mean_share_from_cached_lr_fit()
            # if self.scale_factor is None or (self.global_count is None or self.global_min is None or self.global_max is None):
            #     raise ValueError("Must provide a valid scale_factor or valid (global_count, global_min, global_max)")
            result = local_pre_mean(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, global_min=self.global_min, global_max=self.global_max, global_count=self.global_count, filters=self.filters)
            return result
        if self.computation_type == "stdev":
            result = local_pre_stdev(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, global_min=self.global_min, global_max=self.global_max, filters=self.filters)
            return result
        elif self.computation_type == "mean-stdev":
            if self.over_cached_scores:
                if self.cached_risk_scores is None and self.coeffs is not None:
                    self._run_fused_biomarker_score_computation()
                return self._mean_stdev_share_from_cached_scores()
            result = local_pre_stdev(data_column_id=self.data_column_id, stat_data_path=self.stat_data_path, global_min=self.global_min, global_max=self.global_max, filters=self.filters)
            return result
        elif self.computation_type == "meta-analysis":
            if self.cached_lr_fit is None and self.horizon_threshold is not None:
                self._run_fused_biomarker_lr_fit()
            return self._meta_analysis_share_from_cached_lr_fit()
        elif self.computation_type == "chi2":
            result = local_pre_chi2(stat_data_path=self.stat_data_path,
                                        column_1=self.category_column_1_id,
                                        column_1_categories=self.column_1_categories,
                                        column_2=self.category_column_2_id,
                                        column_2_categories=self.column_2_categories,
                                        scaling_factor=self.scale_factor,
                                        filters=self.filters
                                    )
            return result
        elif self.computation_type == "kaplan-meier":
            from_cached_score, cached_scores = self._km_cached_score_reuse()
            groups_data = local_pre_kaplan_meier(
                                        stat_data_path=self.stat_data_path,
                                        filters=self.filters,
                                        group_col=self.group_column_id,
                                        time_col=self.time_column_id,
                                        censoring_col=self.censoring_column_id,
                                        group_categories=self.group_categories,
                                        time_grid_min=self.time_grid_min,
                                        time_grid_step=self.time_grid_step,
                                        time_grid_max=self.time_grid_max,
                                        is_biomarker_discovery=self.is_biomarker_discovery,
                                        cancer_type=self.cancer_type,
                                        biomarker_covariates=self.biomarker_covariates,
                                        coeffs=self.coeffs,
                                        cutoff_value=self.cutoff_value,
                                        risk_scores=self.risk_scores,
                                        risk_scores_scale_factor=self.risk_scores_scale_factor,
                                        model_key=self.model_key,
                                        from_cached_score=from_cached_score,
                                        cached_scores=cached_scores,
                                    )
            if self.ci_type is not None:
                groups_data = {g: {"N": v["N"], "d": v["d"]} for g, v in groups_data.items()}
            return groups_data
        elif self.computation_type in ENC_BIOMARKER_RISK_GROUP_FAMILY:
            # The split KM consumer preprocesses only to read its own records (harmless; it
            # uploads nothing). The per-patient group trimming happens downstream in the
            # kaplan-meier workflow (risk_scores.iloc[:len_df]), not here.
            records = local_pre_get_biomarker_records(
                                        stat_data_path=self.stat_data_path,
                                        filters=self.filters,
                                        cancer_type=self.cancer_type,
                                        biomarker_covariates=self.biomarker_covariates
                                    )
            return records
        elif self.computation_type in ENC_BIOMARKER_SCORE_FAMILY:
            # Same client-side step as ``biomarker_enc_risk_group_computation``:
            # extract and pack the per-patient covariate matrix for encryption.
            # ``biomarker_enc_score_cache`` (split producer) uses the identical covariate
            # upload; only the server-side tail (neutral pack + cache, no decrypt) differs.
            # ``biomarker_enc_score_postprocess`` (split LCS consumer) runs this preprocess
            # too -- NOT to upload covariates (it uploads none), but to set
            # ``_enc_score_n_patients`` so the round-2 fusion trims the decrypted cache slice
            # to this client's cohort, exactly like the fused scoring path.
            records = local_pre_get_biomarker_records(
                                        stat_data_path=self.stat_data_path,
                                        filters=self.filters,
                                        cancer_type=self.cancer_type,
                                        biomarker_covariates=self.biomarker_covariates
                                    )
            # Patient count: the executor's round-2 fusion trims the batch-aligned
            # slot vector back to this length.
            self._enc_score_n_patients = int(len(records.get("all_records", []) or []))
            return records
        elif self.computation_type == "t-test":
            result = local_pre_t_test(
                                        stat_data_path=self.stat_data_path,
                                        data_column_id=self.data_column_id,
                                        column_1=self.category_column_1_id,
                                        column_1_categories=self.column_1_categories,
                                        global_min=self.global_min,
                                        global_max=self.global_max,
                                        global_count=self.global_count,
                                        filters=self.filters
                                    )
            return result
        else:
            raise ValueError(f"Unsupported computation type: {self.computation_type}")

    def postprocess(self, data):
        '''Data Owner: performs post-processing'''
        self.observed_result = {}
        self.custom_logger.info(f"Post-processing for computation = {self.computation_type}")
        if self.computation_type == "mean":
            if self.cached_lr_field is not None:
                self.observed_result = self._lr_field_post_from_aggregate(data, masked=True)
            else:
                total_sum = data["sum"]
                total_count = data["count"]
                mean = local_post_mean(total_sum, total_count, self.global_min, self.global_max, self.global_count)
                self.observed_result["mean"] = mean
        elif self.computation_type == "stdev":
            numerator = data["numerator"]
            denominator = data["denominator"]
            stdev = local_post_stdev(numerator, denominator, self.global_min, self.global_max)
            self.observed_result["stdev"] = stdev
        elif self.computation_type == "meta-analysis":
            # No mask was applied (we need Σ wₖ in the clear for SE), so the decrypted (sum, count) is directly (Σ wₖ β₁,ₖ, Σ wₖ).
            self.observed_result = local_post_meta_analysis(data["sum"], data["count"], data.get("usable"))
            fused_warning = getattr(self, "_fused_lr_fit_status", None)
            if (
                isinstance(fused_warning, dict)
                and fused_warning.get("status") == "WARN"
                and isinstance(fused_warning.get("warning"), dict)
            ):
                # Each client postprocesses the final aggregate. Preserve that
                # client's local-fit warning in its normal result payload. setdefault:
                # an aggregate-level warning (e.g. too few usable sites) explains the whole
                # result and must not be replaced by this one client's local reason -- but
                # both are kept in ``warnings``.
                self.observed_result.setdefault("warning", fused_warning["warning"])
                self.observed_result.setdefault("warnings", []).append(fused_warning["warning"])
        elif self.computation_type == "mean-stdev":
            count = float(data.get("count", 0) or 0)
            denom = float(data.get("denominator", 0) or 0)
            if count <= 0 or denom <= 0:
                # Empty aggregate (every contributing client had a zero share). Return a graceful FAIL dict instead of dividing by
                # zero; downstream consumers (biomarker_lr_fit etc.) will see the unset cached_scores_mean/std and skip.
                self.observed_result = {
                    "status": "FAIL",
                    "msg": "empty aggregate (count = 0); skipping mean-stdev",
                    "mean": None,
                    "stdev": None,
                }
                if self.over_cached_scores:
                    self.observed_result["mean_scores"] = None
                    self.observed_result["stdev_scores"] = None
                return self.observed_result
            stdev = local_post_stdev(data["numerator"], data["denominator"], self.global_min, self.global_max)
            mean = local_post_mean(data["sum"], data["count"], self.global_min, self.global_max, self.global_count)
            if self.over_cached_scores:
                self.cached_scores_mean = mean
                self.cached_scores_std = stdev
                self.observed_result = {
                    "mean_scores": mean,
                    "stdev_scores": stdev,
                }
            else:
                self.observed_result = {"mean": mean, "stdev": stdev}
            if abs(mean) < _LOW_SNR_THRESHOLD and stdev < _LOW_SNR_THRESHOLD:
                # Mirror the reference-path guard so callers see the same diagnostic on either side.
                logging.getLogger(__name__).warning(
                    "Encrypted mean-stdev below CKKS noise floor: "
                    "|mean|=%.3e, stdev=%.3e, threshold=%.0e. "
                    "Result will be unreliable.",
                    abs(mean), stdev, _LOW_SNR_THRESHOLD,
                )
                try:
                    raise _low_signal_warning(mean, stdev, encrypted=True)
                except WarnException as warning:
                    _attach_warning(self.observed_result, warning)
        elif self.computation_type == "chi2":
            numerator = data["numerator"]
            denominator = data["denominator"]
            dof = data["dof"]
            chi2, p_value = local_post_chi2(numerator, denominator, dof)
            self.observed_result = _chi2_result(chi2, p_value, dof)
        elif self.computation_type == "kaplan-meier":
            numerator_groups = data["numerator_groups"]
            denominator_groups = data["denominator_groups"]
            if self.ci_type is not None:
                # Decrypted data is raw N and d; compute S(t) and log-rank in clear (via utils), then CI
                aggregated_N_groups = numerator_groups
                aggregated_d_groups = denominator_groups
                if 'numerator_A' in data:
                    numerator_A_val = data["numerator_A"]
                    denominator_A_val = data["denominator_A"]
                    numerator_var_A_val = data["numerator_var_A"]
                    denominator_var_A_val = data["denominator_var_A"]
                    S_output, times, chi2, p_value = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups, numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val, masked=False)
                else:
                    logrank_terms = logrank_terms_from_aggregated_N_d(aggregated_N_groups, aggregated_d_groups)
                    if logrank_terms is not None:
                        numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val = logrank_terms
                        S_output, times, chi2, p_value = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups, numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val, masked=False)
                    else:
                        S_output, times = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, aggregated_N_groups, aggregated_d_groups, masked=False)
                        chi2, p_value = None, None
                ci_dict = kaplan_meier_confidence_interval(S_output, aggregated_N_groups, aggregated_d_groups, times, self.ci_type)
                self.observed_result = {"S_output": S_output, "times": times, "CI": ci_dict}
                if chi2 is not None and p_value is not None:
                    self.observed_result["chi2"] = chi2
                    self.observed_result["p_value"] = p_value
            elif 'numerator_A' in data:
                numerator_A_val = data["numerator_A"]
                denominator_A_val = data["denominator_A"]
                numerator_var_A_val = data["numerator_var_A"]
                denominator_var_A_val = data["denominator_var_A"]
                S_output, times, chi2, p_value = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, numerator_groups, denominator_groups, numerator_A_val, denominator_A_val, numerator_var_A_val, denominator_var_A_val, masked=True)
                self.observed_result = {"S_output": S_output, "times": times, "chi2": chi2, "p_value": p_value}
            else:
                S_output, times = local_post_kaplan_meier(self.time_grid_min, self.time_grid_max, self.time_grid_step, numerator_groups, denominator_groups, masked=True)
                self.observed_result = {"S_output": S_output, "times": times}
            if self.model_key == "logistic_reg":    # Swap high_score and low_score because high score means low_risk in logistic regression model. Helps display correctly in the UI.
                # The CI bands are keyed by the same group names and derive from their
                # own curve's (N, d, S), so they must swap together with the curves.
                for block_name in ("S_output", "CI"):
                    block = self.observed_result.get(block_name, None)
                    if block and "high_score" in block and "low_score" in block:
                        high_tmp = block["high_score"]
                        block["high_score"] = block["low_score"]
                        block["low_score"] = high_tmp
            # Same override-visibility rule as the clear path.
            if self.time_grid_max_requested is not None and "warning" not in self.observed_result:
                try:
                    raise _time_grid_clamped_warning(
                        float(self.time_grid_max_requested), float(self.time_grid_max)
                    )
                except WarnException as warning:
                    _attach_warning(self.observed_result, warning)
        elif self.computation_type == "t-test":
            if "status" in data and data["status"] == "FAIL":
                return data["msg"]
            categories = self.column_1_categories
            categories.sort()
            # # Version 1
            # g_n0 = self.scale_factor[categories[0]]
            # g_n1 = self.scale_factor[categories[1]]
            num_d = data['num_d']
            num_den_d = data['num_den_d']
            den_den_d = data['den_den_d']
            num_t = data['num_t']
            den_t = data['den_t']
            t_score, dof, p_value = local_post_t_test(num_d, num_den_d, den_den_d, num_t, den_t, self.global_count)
            self.observed_result = {"t_score": t_score, "dof": dof, "p_value": p_value}
        else:
            raise ValueError(f"Unsupported computation type: {self.computation_type}")
        return self.observed_result

    # ------------------------------------------------------------------
    # Helpers shared by the encrypted and clear-text mean paths when this
    # workflow is reusing ``mean`` to aggregate a cached local LR coefficient
    # (``cached_lr_field``: ``"beta0"`` or ``"beta1"``).
    # ------------------------------------------------------------------
    def _mean_share_from_cached_lr_fit(self):
        """Return ``{"sum": beta * n, "count": n}`` from the cached local LR fit. A degenerate-fit client returns the
        zero-share so the additive aggregation is unaffected.
        """
        if self.cached_lr_fit is None or self.cached_lr_fit.get("status") != "OK":
            return {"sum": 0.0, "count": 0}
        n = int(self.cached_lr_fit["n"])
        beta = float(self.cached_lr_fit[self.cached_lr_field])
        return {"sum": beta * n, "count": n}

    def _lr_field_post_from_aggregate(self, data, masked=False):
        """Server-side: divide ``sum / count`` to recover the ``n``-weighted mean.
        """
        total_sum = float(data["sum"])
        total_count = float(data["count"])
        if total_count <= 0:
            return {
                "status": "FAIL",
                "msg": f"All clients had degenerate cohorts; cannot compute mean of {self.cached_lr_field}.",
                self.cached_lr_field: None,
            }
        return {self.cached_lr_field: total_sum / total_count}

    def _run_fused_biomarker_score_computation(self):
        """Run the local biomarker_score_computation step inline, populating ``cached_risk_scores``.
        """
        scores = local_pre_biomarker_score_computation(
            stat_data_path=self.stat_data_path,
            filters=self.filters,
            cancer_type=self.cancer_type,
            biomarker_covariates=self.biomarker_covariates,
            coeffs=self.coeffs,
        )
        self.cached_risk_scores = scores

    def _run_fused_biomarker_lr_fit(self):
        """Run the local biomarker_lr_fit step inline, populating ``cached_lr_fit``.
        """
        self.cached_lr_fit = None
        scores = self.cached_risk_scores
        mu = self.cached_scores_mean
        sigma = self.cached_scores_std
        if (
            scores is not None
            and len(scores) > 0
            and mu is not None
            and sigma is not None
            and float(sigma) > 0.0
        ):
            self.cached_lr_fit = local_pre_logistic_regression_with_global_zscore(
                stat_data_path=self.stat_data_path,
                filters=self.filters,
                time_col=self.time_column_id,
                censoring_col=self.censoring_column_id,
                horizon_threshold=self.horizon_threshold,
                risk_scores=scores,
                score_mean=float(mu),
                score_std=float(sigma),
                model_key=self.model_key,
                cancer_type=self.cancer_type,
            )
        else:
            self.cached_lr_fit = {
                "status": "FAIL",
                "fail_reason": "no_cached_scores" if not scores else "invalid_score_std",
            }
        if self.cached_lr_fit is None or self.cached_lr_fit.get("status") != "OK":
            logging.getLogger(__name__).warning(
                "meta-analysis (fused lr_fit): local fit degenerate "
                "(scores=%s, mu=%s, sigma=%s, fail_reason=%s); "
                "client will contribute zero share to meta-analysis.",
                "missing" if self.cached_risk_scores is None else f"n={len(self.cached_risk_scores)}",
                self.cached_scores_mean,
                self.cached_scores_std,
                None if self.cached_lr_fit is None else self.cached_lr_fit.get("fail_reason"),
            )
            try:
                raise _degenerate_lr_warning()
            except WarnException as warning:
                self._fused_lr_fit_status = _attach_warning({}, warning)
            if self.cached_lr_fit is not None and self.cached_lr_fit.get("fail_reason"):
                self._fused_lr_fit_status["fail_reason"] = self.cached_lr_fit["fail_reason"]
        else:
            fit = self.cached_lr_fit
            # Same shared-μ/σ per-site fit surfacing as the standalone biomarker_lr_fit.
            self._fused_lr_fit_status = {"status": "OK", "lr_fit": {k: fit[k] for k in ("beta1", "se_beta1", "n", "n_ER", "n_nonER") if k in fit}}

    def _meta_analysis_share_from_cached_lr_fit(self):
        """Return ``{"sum": β₁·w, "count": w}`` with ``w = 1/se_beta1²``.

        After tree-summing across clients, the server holds
        ``A = Σ wₖ·β₁,ₖ`` and ``B = Σ wₖ``. The post-processing helper
        ``local_post_meta_analysis(A, B)`` returns the pooled β̄₁, SE, z, and
        p-value.

        Zero-share cases (additive aggregation is unaffected):
          - ``cached_lr_fit is None`` — degenerate local cohort.
          - ``se_beta1 < 1e-10`` — a near-zero SE would either give an
            infinite weight (one client dominates) or send a NaN through
            the aggregator. We treat this as a degenerate fit too and log
            it so operators can see when it happens.
        """
        _SE_FLOOR = 1e-10
        fit = self.cached_lr_fit
        if fit is None or fit.get("status") != "OK":
            return {"sum": 0.0, "count": 0.0, "usable": 0.0}
        se = float(fit.get("se_beta1", 0.0))
        if se < _SE_FLOOR:
            self.custom_logger.warning(
                f"meta-analysis: local se_beta1={se:.3e} is below the {_SE_FLOOR:.0e} "
                f"floor; sending zero share so this client does not contribute "
                f"(would otherwise be a dominating-weight outlier)."
            )
            return {"sum": 0.0, "count": 0.0, "usable": 0.0}
        w = 1.0 / (se * se)
        beta1 = float(fit["beta1"])
        # ``usable`` tree-sums to the number of sites whose fit passed the gates;
        # the combine is only meaningful with >= 2 (reference contract).
        return {"sum": w * beta1, "count": w, "usable": 1.0}

    def _mean_stdev_share_from_cached_scores(self):
        """Return ``{"sum_sq": Σs², "sum": Σs, "count": n}`` from the cached per-patient scores.

        When ``horizon_threshold`` is set, the moments are restricted to the
        ER-labeled rows (censor-aware, reference section F.2): the shared
        standardization the meta-analysis consumes is defined over those rows
        only. The score cache itself stays unfiltered — KM consumes every
        scored patient. Without a threshold (legacy configs) all cached scores
        are summed, as before.

        After tree-summing across clients, ``sum/count`` is the global mean and
        ``(sum_sq·count - sum²)/(count·(count-1))`` the global sample variance.
        A client with no cohort returns the zero share.

        No data-range normalization is applied (no ``global_min``/``global_max``
        for cached scores): the encrypt path sets ``global_count=None``
        for this branch, so the random masks are used at raw magnitude.
        """
        scores = self.cached_risk_scores or []
        if len(scores) > 0 and self.horizon_threshold is not None:
            time_arr, event_arr = extract_time_event_arrays(
                self.stat_data_path,
                self.filters,
                self.time_column_id,
                self.censoring_column_id,
                cancer_type=self.cancer_type,
            )
            if len(scores) != time_arr.shape[0]:
                # The cache and the extraction must describe the same cohort in the
                # same order; a mismatch is a wiring bug and silently mis-labeling
                # scores would corrupt the shared standardization. Fail loud.
                raise ValueError(
                    f"mean-stdev over cached scores: {len(scores)} cached scores vs "
                    f"{time_arr.shape[0]} extracted time/event rows"
                )
            labeled_mask, _ = censor_aware_er_labels(
                time_arr, event_arr, self.horizon_threshold
            )
            scores = [s for s, keep in zip(scores, labeled_mask) if keep]
        n = int(len(scores))
        if n == 0:
            return {"sum_sq": 0.0, "sum": 0.0, "count": 0}
        s_sum = float(sum(scores))
        s_sum_sq = float(sum(s * s for s in scores))
        return {"sum_sq": s_sum_sq, "sum": s_sum, "count": n}

    def _re_map_batched_patients_biomarker(self, list_scores, batchsize, cov_length):
        """Undo the score packing: slot order -> patient order.

        The packing writes patient ``i`` of a window to slot
        ``i//patients_per_batch + cov_length*(i%patients_per_batch)``. One window holds at most
        ``batchsize`` patients, so a larger cohort arrives as a LIST of windows (one per output
        cipher, in cohort order); each is remapped independently and the results concatenated.
        A single flat list of slots is still accepted for the one-window case.
        """
        cov_length = 2 **(math.ceil(math.log2(cov_length)))  # Rounding to higher power of 2.
        patients_per_batch = batchsize // cov_length

        windows = list_scores
        if not windows:
            return []
        if not isinstance(windows[0], (list, tuple)):
            windows = [windows]          # legacy single-window (flat slot list)

        remapped_list_scores = []
        for window in windows:
            for i in range(len(window)):
                p_idx = i//patients_per_batch + cov_length*(i%patients_per_batch)
                remapped_list_scores.append(window[p_idx])
        return remapped_list_scores

    def compare_reference(self, expected_result):
        if self.computation_type == "kaplan-meier":
            s_output_flag = -1
            for time_iter in range(len(expected_result["times"])):
                for groups in self.observed_result["S_output"]:
                    observed_val = self.observed_result["S_output"][groups][time_iter]
                    expected_val = expected_result["S_output"][groups][time_iter]
                    abs_err = abs(expected_val - observed_val)
                    rel_err = abs_err / max(abs(expected_val), self.abs_floor)
                    if abs_err > self.abs_floor + self.epsilon * abs(expected_val):
                        s_output_flag = expected_result["times"][time_iter]
                        break
                if s_output_flag >= 0:
                    break
            if s_output_flag >= 0:
                self.custom_logger.info(f'Correctness check (S_output{s_output_flag}):  \033[31mFAIL\033[0m ')
            else:
                self.custom_logger.info(f'Correctness check (S_output):  \033[32mPASS\033[0m')

            if "chi2" in expected_result:
                for key in ["chi2", "p_value"]:
                    observed_val = self.observed_result[key]
                    expected_val = expected_result[key]
                    if observed_val is None or expected_val is None:
                        # p_value is None on both sides when the test is degenerate (dof <= 0).
                        verdict = '\033[32mPASS\033[0m' if observed_val is expected_val else '\033[31mFAIL\033[0m'
                        self.custom_logger.info(f'Correctness check ({key}, undefined):  {verdict}')
                        continue
                    abs_err = abs(expected_val - observed_val)
                    rel_err = abs_err / max(abs(expected_val), self.abs_floor)
                    if abs_err <= self.abs_floor + self.epsilon * abs(expected_val):
                        self.custom_logger.info(f'Correctness check ({key}):  \033[32mPASS\033[0m')
                    else:
                        self.custom_logger.info(f'Correctness check ({key}):  \033[31mFAIL\033[0m '
                            f'(abs_err={abs_err:.3e}, rel_err={rel_err:.3e})')

        else:
            for key, expected_val in expected_result.items():
                observed_val = self.observed_result[key]
                abs_err = abs(expected_val - observed_val)
                rel_err = abs_err / max(abs(expected_val), self.abs_floor)
                # pass if within either absolute or relative bound
                if abs_err <= self.abs_floor + self.epsilon * abs(expected_val):
                    self.custom_logger.info(f'Correctness check ({key}):  \033[32mPASS\033[0m')
                else:
                    self.custom_logger.info(f'Correctness check ({key}):  \033[31mFAIL\033[0m '
                        f'(abs_err={abs_err:.3e}, rel_err={rel_err:.3e})')