"""
NVFlareClientEmitManager
------------------------

Given an NVFLARE-assigned job_id (nvflare_assigned_id), this class finds the
corresponding job_runner_id from the nvflare_jobs table, constructs a
JobStatusWriter for it, and logs human-readable progress messages mapped from
numeric codes sent by the NVFlare webhook.

Usage:
    mgr = NVFlareClientEmitManager(job_id_from_webhook)
    mgr.log_progress_from_payload(incoming_json_body)   # maps code -> message, logs
    mgr.complete()
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import time

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.SupportedFunction import FUNCTION_LABELS
from app.core.mysql.job_tracking.JobStatusWriter import (
    JobStatusWriter,
    JobRunnerStatus,
    safe_status_update,
)

_DEDUPE_TTL_SEC = 3.0
# (job_runner_id, site, function_name|None, code, round|-1) -> last_ts
_RECENT_KEYS: dict[Tuple[str, str, str, int, int], float] = {}


HUMAN_MAP = {
    100: "Job broadcast received",

    101: "Executing keygen workflow",

    102: "Executing threshold comparison workflow",

    300: "Parameters loaded",

    410: "Preprocessing (reference)",
    420: "Preprocessing (encrypted)",

    400: "Encrypting local statistics",
    500: "Collaborative decryption",

    600: "Post-processing",

    702: "Results written to JSON",

    # server-only
    710: "Aggregating results from all sources",
    711: "Aggregation complete; running analysis",
    712: "Writing aggregated results to JSON",

    720: "Threshold limit not met",

    900: "Exception encountered",

    # --------------------
    # Encrypted biomarker discovery (workflow_enc_biomarker_disc)
    # Use a dedicated 4-digit namespace (1000-1999) to avoid collisions.
    # --------------------
    1100: "Workflow started",
    1110: "Received encrypted ciphertexts",
    1120: "Loading filters / resolving data paths",

    # will have job label
    1130: "Preprocessing local data",
    1140: "Validating model artifacts",
    1150: "Aggregating encrypted results",
    1160: "Aggregation complete; sending ciphertext",
    1170: "Receiving partial decryptions",
    1180: "Decrypting aggregated results",
    1190: "Risk scores ready; sending to persistor",

    # bootstrap/persistor codes
    1210: "Validating workflow arguments",
    1220: "Loading schema metadata",
    1230: "Validating OpenFHE parameters",
    1240: "Saved risk scores",
}


class NVFlareClientEmitManager:
    """Resolves job_runner_id from an NVFLARE job_id and logs webhook progress."""

    def __init__(self, nvflare_assigned_id: str):
        """
        nvflare_assigned_id: The job_id coming from NVFlare (what the webhook sends).
        """
        self.nvflare_assigned_id = nvflare_assigned_id
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

        self.job_runner_id: Optional[str] = self._lookup_job_runner_id(nvflare_assigned_id)
        self.writer: Optional[JobStatusWriter] = JobStatusWriter(self.job_runner_id) if self.job_runner_id else None

    def complete(self):
        try:
            if self.writer:
                self.writer.complete()
        finally:
            try:
                self.cursor.close()
            finally:
                self.connection.close()

    def _lookup_job_runner_id(self, nvflare_assigned_id: str) -> Optional[str]:
        """Find job_runner_id by NVFlare-assigned job id."""
        sql = f"""
            SELECT job_runner_id
            FROM {MySQLTable.NVFLARE_JOBS}
            WHERE nvflare_assigned_id = %s
            LIMIT 1
        """
        self.cursor.execute(sql, (nvflare_assigned_id,))
        row = self.cursor.fetchone()
        return (row or {}).get("job_runner_id")

    def log_progress_from_payload(self, payload: Dict[str, Any]) -> None:
        """
        Accepts the JSON body the webhook receiver constructed, e.g.:

        {
            "job_id": "...",               # NVFlare id (nvflare_assigned_id)
            "client_name": "site1",
            "phase": 2,
            "round": 0,
            "origin": "site1",
            "timestamp": 1234567890.0,
            "tag": "job_progress",
            "step": 0,                     # mirrors global_step
            "scalars": { "code": 400, "phase_id": 2, "round": 0 },
            "function": "mean"
        }
        """
        scalars = (payload.get("scalars") or {}) if isinstance(payload.get("scalars"), dict) else {}

        code = _to_int(scalars.get("code"))
        rnd = _to_int(scalars.get("round"))

        client = payload.get("origin") or payload.get("client_name")
        function_name = payload.get("function")

        self.log_progress(
            code=code,
            round_num=rnd,
            client_name=client,
            function_name=function_name,
        )

    def log_progress(
        self,
        *,
        code: Optional[int],
        round_num: Optional[int],
        client_name: Optional[str],
        function_name: Optional[str] = None,
    ) -> None:
        if code in (1100, 1110, 1120):
            function_name = "biomarker_enc_risk_group_computation"

        # De-dupe key: use -1 when round is missing (e.g., code 100)
        if self.job_runner_id and client_name and code is not None:
            round_key = int(round_num) if round_num is not None else -1
            fn_key = function_name or ""
            k = (self.job_runner_id, client_name, fn_key, int(code), round_key)
            now = time.time()
            last = _RECENT_KEYS.get(k)
            if last is not None and (now - last) < _DEDUPE_TTL_SEC:
                return
            _RECENT_KEYS[k] = now

        label = HUMAN_MAP.get(code) or f"Event code {code}"
        raw_client = (client_name or "").strip()
        is_server = raw_client.lower() == "initiator" or raw_client.lower() == "server"

        if is_server:
            prefix = "NVFlare Server"
        else:
            client_disp = raw_client or "?"
            prefix = f"Client {client_disp}"

        pretty_function = None
        if function_name:
            pretty_function = FUNCTION_LABELS.get(function_name, function_name)
        fn_prefix = f"[{pretty_function}] " if pretty_function else ""

        if round_num is None:
            msg = f"{prefix}: {fn_prefix}{label}".strip()
        else:
            try:
                round_disp = int(round_num) + 1  # 1-indexed for humans
            except Exception:
                round_disp = "?"
            msg = f"{prefix}: {fn_prefix}{label} (round {round_disp})".strip()

        status = _resolve_status(code, is_server)
        safe_status_update(self.writer, status, msg)


def _resolve_status(code: Optional[int], is_server: bool) -> JobRunnerStatus:
    if code == 100:
        return JobRunnerStatus.JOB_RECEIVED

    if code == 720:
        return JobRunnerStatus.THRESHOLD_NOT_MET

    if code == 900:
        return JobRunnerStatus.ERROR

    # The sample-count pre-pass is a two-round encrypt/decrypt exchange like any other
    # computation, so it drives the compute step of the status flow rather than a step of
    # its own; the round-by-round detail is carried by the log message.
    if code in {102, 300, 1120, 1140, 1210, 1220}:
        return JobRunnerStatus.SERVER_COMPUTE if is_server else JobRunnerStatus.CLIENT_COMPUTE


    if code in {101}:
        return JobRunnerStatus.KEYGEN_WORKFLOW
    
    if code in {500}:
        return JobRunnerStatus.DECRYPTION

    if code in {400, 420, 500, 1110, 1150, 1160, 1170, 1180, 1230}:
        return JobRunnerStatus.SERVER_ENCRYPTION if is_server else JobRunnerStatus.CLIENT_ENCRYPTION

    if code in {410, 711, 1100, 1130}:
        return JobRunnerStatus.SERVER_ANALYSIS if is_server else JobRunnerStatus.CLIENT_ANALYSIS

    if code in {600, 702, 710, 712, 1190, 1240}:
        return JobRunnerStatus.SERVER_RESULTS if is_server else JobRunnerStatus.CLIENT_RESULTS

    return JobRunnerStatus.PROCESSING


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None