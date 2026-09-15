"""Test-only probe recording how the biomarker high/low binning actually resolved.

``conftest._stage_job`` copies this module into a staged simulator job's client
``custom/`` folder and registers it as a client component there. It therefore exists
only inside a job the sweep itself staged: neither the shipped wheel nor the
production job template references it, so whether individual patients were re-binned
stays unobservable in a deployment. Enabling it somewhere real would mean placing a
Python module on the client's filesystem, not setting an environment variable.

It wraps ``local_pre_kaplan_meier`` -- the one function both the encrypted and the
clear Kaplan-Meier chains bin through -- and records per call:

* which path ran (``encrypted`` / ``clear_cached`` / ``clear_recompute``);
* each arm's occupancy of every ``(time cell, event?)`` bucket, which is a sufficient
  statistic for that arm's Kaplan-Meier contribution, so the sweep can diff the
  encrypted run against the clear reference and count exactly how many patients
  changed arm -- including swaps that leave the arm sizes unchanged; and
* the clear path's count of patients sitting within ``NEAR_CUTOFF_MARGIN`` of the
  cutoff, whose arm therefore cannot be guaranteed, separating an inevitable
  re-binning from a genuine divergence.

That count is taken from the reference path deliberately. The encrypted path only
ever sees ``rm * rsf * (score - cutoff)``, and ``rm`` is redrawn per patient per run
across five orders of magnitude, so a count measured there would describe the run's
mask draw rather than the cohort. The clear path knows the exact ``score - cutoff``
and gives the same answer every run.

Aggregate only: arm bucket totals and one integer per cohort. No per-patient score or
margin is recorded anywhere.
"""

from __future__ import annotations

import json
import os
import sys

from nvflare.apis.fl_component import FLComponent

# Set by the conftest fixture to a path under the case's own tmp_path.
OUTPUT_ENV = "SIM_BINNING_PROBE"

# The clear path counts its own near-cutoff patients and hangs the total on the frame
# it returns; this carries that total from there to the record emitted for the same
# cohort. Client tasks run one at a time in a process, so a single slot suffices.
_pending_near_cutoff: dict = {"count": None}


def _client_name() -> str:
    """Site name from the simulator worker's argv (``--client site1``)."""
    argv = sys.argv
    if "--client" in argv:
        index = argv.index("--client")
        if index + 1 < len(argv):
            return str(argv[index + 1])
    return "unknown"


def _emit(record: dict) -> None:
    path = os.environ.get(OUTPUT_ENV, "").strip()
    if not path:
        return
    # One short line per open/append: concurrent client processes share this file and
    # O_APPEND keeps single small writes from interleaving.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _arm_composition(groups_data) -> dict:
    """Per-arm occupancy of each ``(time cell, event?)`` bucket.

    ``N[i]`` is the number at risk at grid index ``i`` and ``d[i]`` the events there,
    so ``N[i] - N[i+1]`` is how many members sit in cell ``i`` and ``d[i]`` splits them
    into events and censored. Those buckets are a sufficient statistic for the arm:
    the survival curve ``prod(1 - d_i/n_i)`` and the log-rank chi2 are functions of
    nothing else. Two runs whose buckets match therefore produce identical Kaplan-Meier
    output by construction, and any difference in the reported numbers is numerical.

    Returns ``{arm: {"n": size, "cells": [[index, events, censored], ...]}}`` with only
    occupied cells listed. Counts per cell, never a patient.
    """
    composition = {}
    if not isinstance(groups_data, dict):
        return composition
    for arm, payload in groups_data.items():
        try:
            at_risk = [int(round(float(v))) for v in payload["N"]]
            events = [int(round(float(v))) for v in payload["d"]]
        except (KeyError, TypeError, ValueError):
            continue
        if not at_risk or len(events) != len(at_risk):
            continue
        cells = []
        for index in range(len(at_risk)):
            # Members whose mapped event time falls in this cell. The last cell has no
            # successor to subtract, and the sum telescopes back to N[0].
            here = at_risk[index] - (at_risk[index + 1] if index + 1 < len(at_risk) else 0)
            if here or events[index]:
                cells.append([index, events[index], here - events[index]])
        composition[str(arm)] = {"n": at_risk[0], "cells": cells}
    return composition


def _kind(kwargs: dict) -> str:
    """Which of the three binning paths this call took."""
    if kwargs.get("risk_scores") is not None:
        return "encrypted"
    if kwargs.get("from_cached_score"):
        return "clear_cached"
    return "clear_recompute"


def _wrap(original):
    def probed(*args, **kwargs):
        # Cleared first so a stale count from an earlier cohort can never attach here.
        _pending_near_cutoff["count"] = None
        result = original(*args, **kwargs)
        try:
            if kwargs.get("is_biomarker_discovery"):
                near_cutoff = _pending_near_cutoff["count"]
                record = {
                    "site": _client_name(),
                    "kind": _kind(kwargs),
                    "model_key": kwargs.get("model_key"),
                    "cutoff": kwargs.get("cutoff_value"),
                    "scale_factor": kwargs.get("risk_scores_scale_factor"),
                    "arms": _arm_composition(result),
                }
                if near_cutoff is not None:
                    record["near_cutoff"] = int(near_cutoff)
                _emit(record)
        except Exception as exc:  # a probe must never break the run it observes
            _emit({"site": _client_name(), "error": repr(exc)})
        return result

    probed._binning_probe = True
    return probed


def _wrap_km_dataframe(original):
    """Carry the clear path's near-cutoff count off the frame it hangs it on."""

    def probed(*args, **kwargs):
        frame = original(*args, **kwargs)
        try:
            _pending_near_cutoff["count"] = frame.attrs.get(NEAR_CUTOFF_ATTR)
        except Exception:
            _pending_near_cutoff["count"] = None
        return frame

    probed._binning_probe = True
    return probed


NEAR_CUTOFF_ATTR = "biomarker_near_cutoff"


def install() -> None:
    """Wrap the binning entry points in this client process. Idempotent."""
    global NEAR_CUTOFF_ATTR
    try:
        from duality_nvflare_apis import stat_analytics, utils
        from duality_nvflare_apis.fhir import filter_engine_config
    except Exception as exc:
        _emit({"site": _client_name(), "error": f"probe import failed: {exc!r}"})
        return
    if getattr(utils.local_pre_kaplan_meier, "_binning_probe", False):
        return
    NEAR_CUTOFF_ATTR = getattr(filter_engine_config, "NEAR_CUTOFF_ATTR", NEAR_CUTOFF_ATTR)

    probed = _wrap(utils.local_pre_kaplan_meier)
    utils.local_pre_kaplan_meier = probed
    # ``stat_analytics`` did ``from .utils import local_pre_kaplan_meier`` at import
    # time and holds its own reference, so rebinding ``utils`` alone would miss every
    # real call site.
    stat_analytics.local_pre_kaplan_meier = probed

    # The scoring frame never escapes ``local_pre_kaplan_meier``, so the count has to be
    # taken where it is produced. ``build_biomarker_km_dataframe`` calls this by module
    # global, so patching the module attribute catches it however the engine is resolved.
    filter_engine_config.biomarker_subjects_to_km_dataframe = _wrap_km_dataframe(
        filter_engine_config.biomarker_subjects_to_km_dataframe
    )


class BinningProbe(FLComponent):
    """Client component whose only job is to install the wrapper at app start."""

    def __init__(self):
        super().__init__()
        install()
