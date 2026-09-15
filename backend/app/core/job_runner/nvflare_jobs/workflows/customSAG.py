import logging
from typing import Any, Dict, Optional

from nvflare.app_common.workflows.scatter_and_gather import ScatterAndGather
from nvflare.apis.fl_context import FLContext
from nvflare.apis.controller_spec import ClientTask, SendOrder, Task
from nvflare.app_common.app_constant import AppConstants
from nvflare.apis.dxo import DXO, DataKind, from_shareable
from nvflare.apis.shareable import Shareable
from nvflare.apis.signal import Signal
from nvflare.apis.fl_constant import ReservedKey

# Constants for metadata keys
META_TARGET_CLIENTS = "_TARGET_CLIENTS_"
META_PER_CLIENT_PAYLOADS = "_PER_CLIENT_PAYLOADS_"
META_FLAG_SKIP_WORKFLOW = "FLAG_SKIP_WORKFLOW"

_audit_logger = logging.getLogger("custom.audit_log")


def _effective_shareable_for_client(
    shareable: Shareable,
    client_name: str,
    workload_args: Optional[Dict[str, Any]] = None,
    is_first_round: bool = False,
) -> Shareable:
    """
    Build the Shareable to send to one client from the aggregator's (possibly asymmetric) Shareable.
    Avoids copying base data when the client gets the base payload only.
    """
    dxo = from_shareable(shareable)
    base_data = dxo.data if dxo.data is not None else {}
    base_meta = dict(dxo.meta) if dxo.meta else {}
    per_client_specs = base_meta.pop(META_PER_CLIENT_PAYLOADS, None)  # base_meta is now clean for clients

    _branch = None  # diagnostic: which payload this client received (base / merge / override)
    # No per-client specs or client not listed: client gets base (reuse refs, no copy)
    if not per_client_specs or client_name not in per_client_specs:
        meta_clean = base_meta
        data = base_data
        _branch = "base(no_specs)" if not per_client_specs else "base(client_absent)"
    else:
        spec = per_client_specs.get(client_name)
        if spec is None or (isinstance(spec, dict) and len(spec) == 0):
            meta_clean = base_meta
            data = base_data
            _branch = "base(empty_spec)"
        elif isinstance(spec, dict) and spec.get("_override_"):
            # Client gets only override data/meta (no base)
            data = spec.get("data", {})
            meta_clean = dict(spec.get("meta", {}))
            _branch = "override"
        else:
            # Merge base + extra (one copy for this client only)
            extra_data = (spec.get("_extra_data_") or {}) if isinstance(spec, dict) else {}
            extra_meta = (spec.get("_extra_meta_") or {}) if isinstance(spec, dict) else {}
            data = {**base_data, **extra_data}
            meta_clean = {**base_meta, **extra_meta}
            _branch = "merge"

    # Round-3 PQC dispatch diagnostic: fires only on asymmetric (per-client) dispatches, i.e. the
    # round where META_PER_CLIENT_PAYLOADS is set. Shows the per_client_specs keys AS SEEN AT DISPATCH
    # (vs. the server's construction-time log) + whether this client got a result-bearing payload, to
    # localize an intermittent round-3 None: a "base(...)" branch with result_present=False is the drop.
    if per_client_specs is not None:
        try:
            _audit_logger.info(
                "PQC round-3 dispatch: client=%s round=%s in_specs=%s spec_keys=%s branch=%s result_present=%s",
                client_name,
                base_meta.get("round"),
                (isinstance(per_client_specs, dict) and client_name in per_client_specs),
                sorted(per_client_specs.keys()) if isinstance(per_client_specs, dict) else type(per_client_specs).__name__,
                _branch,
                (isinstance(data, dict) and data.get("result") is not None),
            )
        except Exception:
            pass

    data_kind = getattr(dxo, "data_kind", DataKind.WEIGHTS)
    effective_dxo = DXO(data_kind=data_kind, data=data, meta=meta_clean)
    if is_first_round and workload_args is not None:
        effective_dxo.set_meta_prop("workload_args", workload_args)
    return effective_dxo.to_shareable()

class customSAG(ScatterAndGather):
    """
    A thin wrapper over ScatterAndGather:
        1. Injects per-workflow workload parameters into the aggregator and persistor.
        2. Allows min_clients = 0 (aggregation only after all clients respond).
        3. Allows skipping workflows.
        4. Allows targeting specific clients (_TARGET_CLIENTS_).
        5. Handles KeyGen optimization.
        6. Asymmetric payloads: when aggregator returns a Shareable with _PER_CLIENT_PAYLOADS_,
           all clients are contacted; each receives a tailored payload (base, base+extra, or override)
           without duplicating the base data in memory. See HEAggregator.get_shareable_data_asymmetric.
    """
    def __init__(self, workload_args: dict | None = None, **kwargs):
        flag_aggregate_iff_all_clients = False  # Flag used to allow min_clients = 0 in ScatterAndGather. If so, aggregation will only start after all clients responses are received.
        if "min_clients" in kwargs and kwargs["min_clients"] == 0:
            flag_aggregate_iff_all_clients = True
            kwargs["min_clients"] = 1000    # Setting to ScatterAndGather's default high value to avoid ValueError = 0.
        super().__init__(**kwargs)
        self.workload_args = workload_args or {}
        if flag_aggregate_iff_all_clients:
            self._min_clients = 0    # Resetting to 0 after parent init.

    def start_controller(self, fl_ctx: FLContext):
        # Add workload_args to fl_ctx so that aggregator and persistor can access them.
        fl_ctx.set_prop("workload_args", self.workload_args, private=True, sticky=True)

        # Skip the workflow if the workflow is marked for skipping.
        skip_workflow = fl_ctx.get_prop(META_FLAG_SKIP_WORKFLOW, None)
        if skip_workflow is not None:
            if fl_ctx.get_prop(ReservedKey.WORKFLOW) in skip_workflow and skip_workflow[fl_ctx.get_prop(ReservedKey.WORKFLOW)] == True:
                self.log_info(fl_ctx, "Workflow is marked to be skipped. Empty initialization.")
                return

        super().start_controller(fl_ctx)

        # Added to avoid extra round of communication or exposing server sk to global weights.
        if self.persistor and self.train_task_name == "task_KeyGen":
            self.aggregator.set_sk(self.persistor.get_aggregator_sk())


    def control_flow(self, abort_signal: Signal, fl_ctx: FLContext) -> None:
        # Skip the workflow if the workflow is marked for skipping.
        skip_workflow = fl_ctx.get_prop(META_FLAG_SKIP_WORKFLOW, None)
        if skip_workflow is not None:
            if fl_ctx.get_prop(ReservedKey.WORKFLOW) in skip_workflow and skip_workflow[fl_ctx.get_prop(ReservedKey.WORKFLOW)] == True:
                self.log_info(fl_ctx, "Workflow is marked to be skipped. Skipping scheduling the workflow.")
                return

        super().control_flow(abort_signal, fl_ctx)


    def _prepare_train_task_data(self, client_task: ClientTask, fl_ctx: FLContext) -> None:
        # This callback runs right before sending to each client. Support asymmetric payloads.
        shareable = client_task.task.data
        current_round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        start_round = fl_ctx.get_prop(AppConstants.START_ROUND)
        is_first_round = current_round == start_round

        try:
            dxo = from_shareable(shareable)
            per_client = dxo.get_meta_prop(META_PER_CLIENT_PAYLOADS, None)
        except Exception:
            per_client = None

        if per_client is not None:
            # Asymmetric: build client-specific payload. Mutate task.data in place so the controller
            # (which may hold the original Task reference when serializing) sends this client's payload.
            client_name = client_task.client.name
            effective = _effective_shareable_for_client(
                shareable, client_name,
                workload_args=self.workload_args,
                is_first_round=is_first_round,
            )
            client_task.task.data = effective
        else:
            # Symmetric: inject workload_args only for the first round (standard behavior).
            if is_first_round:
                dxo = from_shareable(shareable)
                dxo.set_meta_prop("workload_args", self.workload_args)
                client_task.task.data = dxo.to_shareable()

        # Preserve default behavior (fires BEFORE_TRAIN_TASK event, etc.)
        super()._prepare_train_task_data(client_task, fl_ctx)


    def broadcast_and_wait(self, fl_ctx: FLContext, task, min_responses: int, wait_time_after_min_received: int, abort_signal: Signal | None):
        """
        Override the default broadcast behavior.
        - If task has _PER_CLIENT_PAYLOADS_: send a separate Task to each client with that client's
          payload (sequential send_and_wait per client). The framework's broadcast uses one Task and
          calls before_task_sent_cb when each client requests; the payload we set there is not
          guaranteed to be the one sent (e.g. request order / locking can make the wrong payload go out).
          So for asymmetric we bypass broadcast and send one task per client explicitly.
        - Else if task has _TARGET_CLIENTS_ (subset): send_and_wait to those targets only.
        - Else: broadcast to all.
        """
        target_clients = None
        per_client_payloads = None

        try:
            dxo = from_shareable(task.data)
            per_client_payloads = dxo.get_meta_prop(META_PER_CLIENT_PAYLOADS, None)
            target_clients = dxo.get_meta_prop(META_TARGET_CLIENTS, None)
        except Exception as e:
            self.log_warning(fl_ctx, f"Failed to extract DXO from shareable: {e}. Falling back to default broadcast.")

        # Asymmetric payloads: send one task per selected client (parallel), then wait for all.
        #
        # Important: asymmetric shareables can carry a sparse per-client map. In the hide-result
        # workflow the base payload is intentionally empty, and only the clients listed in
        # _TARGET_CLIENTS_ have a real per-client PQC payload. Sending the empty base payload to
        # every client makes unlisted clients enter round 3 with result=None.
        if per_client_payloads is not None:
            engine = fl_ctx.get_engine()
            all_clients = engine.get_clients()
            current_round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
            start_round = fl_ctx.get_prop(AppConstants.START_ROUND)
            is_first_round = current_round == start_round

            def _client_name(client) -> str:
                return client.name if hasattr(client, "name") else str(client)

            selected_clients = list(all_clients)
            if target_clients is not None and target_clients != "@ALL":
                if isinstance(target_clients, list):
                    target_names = {str(name) for name in target_clients}
                    selected_clients = [client for client in all_clients if _client_name(client) in target_names]
                    selected_names = {_client_name(client) for client in selected_clients}
                    missing_names = sorted(target_names - selected_names)
                    if missing_names:
                        self.log_warning(fl_ctx, f"Asymmetric payload target clients were not connected: {missing_names}")
                else:
                    self.log_warning(
                        fl_ctx,
                        f"Invalid type for {META_TARGET_CLIENTS}: {type(target_clients)}. Sending asymmetric payload to all clients.",
                    )

            self.log_info(
                fl_ctx,
                "Asymmetric payloads: sending one task per selected client "
                f"(parallel send, then wait for all). targets={[ _client_name(c) for c in selected_clients ]}",
            )

            # Fire same before_task_sent as parent (TRAIN_SHAREABLE, BEFORE_TRAIN_TASK)
            def _before_send(client_task: ClientTask, fl_ctx: FLContext):
                super(customSAG, self)._prepare_train_task_data(client_task, fl_ctx)

            tasks_sent = []
            for client in selected_clients:
                if abort_signal is not None and abort_signal.triggered:
                    break
                client_name = _client_name(client)
                effective = _effective_shareable_for_client(
                    task.data,
                    client_name,
                    workload_args=self.workload_args,
                    is_first_round=is_first_round,
                )
                # Set controller headers so client/profiler see correct round (same as broadcast path)
                effective.set_header(AppConstants.CURRENT_ROUND, current_round)
                effective.set_header(AppConstants.NUM_ROUNDS, fl_ctx.get_prop(AppConstants.NUM_ROUNDS, 0))
                effective.set_header(AppConstants.START_ROUND, fl_ctx.get_prop(AppConstants.START_ROUND, current_round))
                effective.add_cookie(AppConstants.CONTRIBUTION_ROUND, current_round)
                task_for_client = Task(
                    name=task.name,
                    data=effective,
                    operator=getattr(task, "operator", None),
                    props=getattr(task, "props", {}),
                    timeout=getattr(task, "timeout", 0),
                    before_task_sent_cb=_before_send,
                    result_received_cb=task.result_received_cb,
                )
                self.send(
                    task=task_for_client,
                    fl_ctx=fl_ctx,
                    targets=[client],
                    send_order=SendOrder.ANY,
                    task_assignment_timeout=0,
                )
                tasks_sent.append(task_for_client)

            for t in tasks_sent:
                if abort_signal is not None and abort_signal.triggered:
                    break
                self.communicator.wait_for_task(t, abort_signal)

            # Round-2 wait-race fix. Observed failure: wait_for_task() above returned ~0.2s after the
            # leader was sent its task, BEFORE the leader finished its ~1s HE payload build and submitted.
            # The parent control_flow then called aggregate() with an incomplete accepted_data; in a PQC
            # round-2 that makes the leader's per-non-leader payloads absent, the round_idx==2 guard
            # raises, the generic handler swallows it into an empty payload, and the non-leaders get a
            # result-less round-3 task (an intermittent None). See the server-side guard in
            # analytics_aggregator_impl.py.
            #
            # Barrier: do not let this round complete until every per-client task has actually completed.
            # This only waits for work that is already on the critical path (the next aggregate genuinely
            # needs these results), so it adds no avoidable wall-clock; it is bounded by abort_signal and
            # the task timeout so a genuinely dead client cannot hang the job.
            self._await_asymmetric_completion(tasks_sent, abort_signal, fl_ctx)
            return

        # Symmetric: optional target subset
        should_broadcast = True
        if target_clients is not None and target_clients != "@ALL":
            if isinstance(target_clients, list):
                engine = fl_ctx.get_engine()
                all_clients = engine.get_clients()
                if len(target_clients) < len(all_clients):
                    should_broadcast = False
                else:
                    self.log_info(fl_ctx, f"Target list length ({len(target_clients)}) equals total clients. Broadcasting.")
            else:
                self.log_warning(fl_ctx, f"Invalid type for {META_TARGET_CLIENTS}: {type(target_clients)}. Expected List. Broadcasting.")

        if should_broadcast:
            self.log_info(fl_ctx, "Broadcasting task to all clients.")
            return super().broadcast_and_wait(
                task=task, fl_ctx=fl_ctx, min_responses=min_responses,
                wait_time_after_min_received=wait_time_after_min_received, abort_signal=abort_signal,
            )
        self.log_info(fl_ctx, f"Multicasting task to specific targets: {target_clients}")
        return self.send_and_wait(
            task=task,
            fl_ctx=fl_ctx,
            targets=target_clients,
            send_order=SendOrder.ANY,
            task_assignment_timeout=0,
            abort_signal=abort_signal,
        )

    def _await_asymmetric_completion(self, tasks_sent, abort_signal, fl_ctx, poll_s: float = 0.05):
        """Block until every per-client task from this asymmetric round has actually completed.

        Closes the intermittent round-3 PQC payload-None wait race: wait_for_task() can return
        before a slow client's result is received, letting control_flow advance to aggregate() with an
        incomplete accepted_data -- in a PQC round-2 that drops the leader's per-non-leader payloads and
        the non-leaders get a result-less round-3 payload (the intermittent None). By the time we get
        here the per-task waits should already have returned, so this is normally a no-op; it only blocks
        when a result is genuinely still outstanding (e.g. the leader's slow HE payload build), which the
        next aggregate needs anyway -- so no avoidable wall-clock is added. Bounded by abort_signal and
        the per-task timeout (fallback 600s) so a dead client cannot hang the job.

        Readiness = every per-Task `completion_status` set. Validated against the standalone repro
        (4 runs, 2026-06-22): caught a 0.60s leader-late round-2 race and corrected it, 0 timeouts, 0
        round-3 None drops. (An earlier draft also A/B'd an `accepted_data`-based gate; it was rejected
        because terminal-round non-leaders receive their result but never re-submit, so they never enter
        accepted_data and that gate would hang. `completion_status` is the correct, universal signal.)
        """
        import time

        timeouts = [getattr(t, "timeout", 0) or 0 for t in tasks_sent]
        max_wait_s = max(timeouts) if any(timeouts) else 600.0

        waited = 0.0
        pending_tasks = tasks_sent
        while waited < max_wait_s:
            if abort_signal is not None and abort_signal.triggered:
                return
            pending_tasks = [t for t in tasks_sent if getattr(t, "completion_status", None) is None]
            if not pending_tasks:
                if waited > 0:
                    self.log_info(
                        fl_ctx,
                        f"_await_asymmetric_completion: waited {waited:.2f}s for {len(tasks_sent)} task(s) "
                        f"to complete before aggregate (closed the round-2 wait race).",
                    )
                return
            time.sleep(poll_s)
            waited += poll_s

        self.log_warning(
            fl_ctx,
            f"_await_asymmetric_completion: {len(pending_tasks)} task(s) still pending after "
            f"{max_wait_s:.0f}s; proceeding to aggregate. If this fires, a client never returned its "
            f"round result.",
        )