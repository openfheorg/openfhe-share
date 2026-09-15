import time
import pymysql

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.MySQLTable import MySQLTable
pymysql.install_as_MySQLdb()
import MySQLdb


class JobStatusRetriever:
    def __init__(self, max_retries: int = 3, base_delay: float = 0.2):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def _exec(self, query: str, params: tuple, fetch: str = "one"):
        delay = self.base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                self.cursor.execute(query, params)
                return self.cursor.fetchone() if fetch == "one" else self.cursor.fetchall()
            except Exception:
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2

    def get_status_by_uuid(self, uuid: str):
        row = self._exec(
            f"SELECT * FROM {MySQLTable.JOB_RUNNER_LOG} WHERE uuid = %s",
            (uuid,),
            fetch="one",
        )
        if row:
            referenced = self._exec(
                f"""
                SELECT
                    id,
                    nvflare_assigned_id,
                    run_duration
                FROM {MySQLTable.NVFLARE_JOBS}
                WHERE job_runner_id = %s
                """,
                (uuid,),
                fetch="all",
            )

            row["referenced_by"] = [r["nvflare_assigned_id"] for r in referenced if r.get("nvflare_assigned_id")]
            durations = [r["run_duration"] for r in referenced if r.get("run_duration")]
            row["run_duration"] = durations[0] if durations else ""

            valid_nvflare_jobs = [r for r in referenced if r.get("id") is not None]

            if valid_nvflare_jobs:
                job_ids = [r["id"] for r in valid_nvflare_jobs]
                placeholders = ",".join(["%s"] * len(job_ids))
                function_rows = self._exec(
                    f"""
                    SELECT
                        njf.job_id,
                        df.name
                    FROM {MySQLTable.NVFLARE_JOB_FUNCTIONS} njf
                    JOIN {MySQLTable.FUNCTIONS} df
                      ON df.id = njf.function_id
                    WHERE njf.job_id IN ({placeholders})
                    ORDER BY njf.job_id, df.name
                    """,
                    tuple(job_ids),
                    fetch="all",
                )

                functions_by_job = {}
                for function_row in function_rows:
                    job_id = function_row["job_id"]
                    function_name = function_row["name"]
                    if job_id not in functions_by_job:
                        functions_by_job[job_id] = []
                    functions_by_job[job_id].append(function_name)

                row["nvflare_jobs"] = []
                all_functions = set()

                for nvflare_job in valid_nvflare_jobs:
                    job_id = nvflare_job["id"]
                    job_functions = functions_by_job.get(job_id, [])
                    row["nvflare_jobs"].append(
                        {
                            "id": job_id,
                            "nvflare_assigned_id": nvflare_job["nvflare_assigned_id"],
                            "run_duration": nvflare_job["run_duration"],
                            "functions": job_functions,
                        }
                    )
                    all_functions.update(job_functions)

                row["functions"] = sorted(all_functions)

        return row

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()
