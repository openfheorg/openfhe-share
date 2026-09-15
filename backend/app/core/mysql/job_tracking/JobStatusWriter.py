'''
This class is used to create/update entries in the job runner log table. 
A running task will print updates to the log column and keep a running log 
that can be retrieved by the job status endpoint. The log accumulates messages 
with timestamps, while the status column reflects the latest state of the job.
'''

from enum import Enum
import os
import threading
import traceback
from typing import Optional
from datetime import datetime, timezone

import pymysql

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
from app.core.mysql.MySQLTable import MySQLTable
pymysql.install_as_MySQLdb()
import MySQLdb

    
class JobRunnerStatus(str, Enum):
    # Enum of all possible states a job can be in. 
    # Covers the whole lifecycle: queued, filter processing, ssh setup, 
    # upload, definition, broadcast, analysis, result aggregation, and final DONE. 
    # Also includes error states like FAILURE, WARNING, and ERROR.
    # Using str Enum means each entry stringifies to its label automatically.    
    QUEUED = "Queued"
    PROCESSING = "Processing"
    
    PARTICIPATION_INITIAL_CHECK = "Checking Client Participation"
    PARTICIPATION_BROADCAST = "Broadcasting Participation Job"
    PARTICIPATION_MONITORING = "Monitoring Participation Responses"
    PARTICIPATION_ESTABLISHED = "Client Participation Established"
    PARTICIPATION_FAILED = "Participation Failed"
    PARTICIPATION_EMPTY = "No Clients Accepted Participation"

    FILTERS_PROCESSING = "Processing Filters"
    
    ESTABLISHING_SECURE_CONNECTION = "Establishing Secure Connection"
    SECURE_CONNECTION_ESTABLISHED = "Secure Connection Established"

    JOB_UPLOAD = "Uploading NVFlare Job"
    JOB_DEFINING = "Defining NVFlare Job"
    JOB_BROADCAST = "Broadcasting NVFlare Job"
    JOB_RECEIVED = "Job Broadcast Received"

    CLIENT_COMPUTE = "Client Compute"
    SERVER_COMPUTE = "Server Compute"

    KEYGEN_WORKFLOW = "Interactive Key Generation"

    DECRYPTION = "Collaborative Decryption"

    CLIENT_ENCRYPTION = "Client Encryption Processing"
    SERVER_ENCRYPTION = "Server Encryption Processing"

    CLIENT_ANALYSIS = "Client Performing Analysis"
    SERVER_ANALYSIS = "Server Performing Analysis"

    CLIENT_RESULTS = "Client Processing Results"
    SERVER_RESULTS = "Server Processing Results"

    JOB_ANALYSIS = "Performing Analysis"
    JOB_RESULTS = "Aggregating Job Results"
    
    THRESHOLD_NOT_MET = "Threshold Not Met"
    ANALYSIS_FAILURE = "Analysis Failure"
    
    FAILURE = "Failure"
    WARNING = "Warning"
    ERROR = "Error"
    DONE = "DONE"

    def __str__(self):
        return self.value

class JobStatusWriter:
    
    def __init__(self, job_id: str):
        # Tied to a single job_id (uuid assigned by JobRunnerService).
        # Opens a pooled DB connection and DictCursor right away. 
        # We also hold a threading lock so that concurrent log() calls
        # for the same job don’t interleave writes into the DB.        
        self.job_id = job_id
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)
        self.status_lock = threading.Lock()

    def complete(self):
        self.cursor.close()
        self.connection.close()

    def get_job_id(self):
        return self.job_id

    def log(self, log_message: Optional[str], status: JobRunnerStatus = None):
        # Core logging method. 
        # Builds a timestamped log line and appends it into JOB_RUNNER_LOG for this job_id.
        # If a status is passed, it also updates the job’s current status column. 
        #
        # Special case: if the DB row has been manually set to STOP, 
        # the writer will log that fact, update the row, and then hard-exit the process. 
        # This gives admins a kill switch for runaway jobs.
        #
        # Uses INSERT ... ON DUPLICATE KEY UPDATE so that each log entry 
        # is appended to the existing log text column.
        if not log_message:
            return
        
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        full_message = f"[{timestamp}] {log_message}"

        with self.status_lock:
            try:
                self.cursor.execute(
                    "SELECT 1 FROM " + MySQLTable.JOB_RUNNER_LOG + " WHERE uuid = %s AND status = 'STOP' LIMIT 1",
                    (self.job_id,)
                )
                if self.cursor.fetchone():
                    full_message = f"[{timestamp}] Job {self.job_id} is marked as STOP in DB. Exiting."

                    self.cursor.execute(
                        """
                        INSERT INTO """ + MySQLTable.JOB_RUNNER_LOG + """ (uuid, log)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE
                            log = CONCAT(IFNULL(log, ''), '\n', VALUES(log)),
                            update_date = CURRENT_TIMESTAMP
                        """,
                        (self.job_id, full_message)
                    )
                    self.connection.commit()
                    # Terminate container if status manually set to STOP:
                    os._exit(0)
            except MySQLdb.Error:
                traceback.print_exc()

            try:
                if status is not None:
                    self.cursor.execute(
                        """
                        INSERT INTO """ + MySQLTable.JOB_RUNNER_LOG + """ (uuid, log, status)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            log = CONCAT(IFNULL(log, ''), '\n', VALUES(log)),
                            status = VALUES(status),
                            update_date = CURRENT_TIMESTAMP
                        """,
                        (self.job_id, full_message, str(status))
                    )
                else:
                    self.cursor.execute(
                        """
                        INSERT INTO """ + MySQLTable.JOB_RUNNER_LOG + """ (uuid, log)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE
                            log = CONCAT(IFNULL(log, ''), '\n', VALUES(log)),
                            update_date = CURRENT_TIMESTAMP
                        """,
                        (self.job_id, full_message)
                    )
                self.connection.commit()
            except Exception:
                traceback.print_exc()


def safe_status_update(sql_status_writer: JobStatusWriter=None, status: JobRunnerStatus = None, message: str = ""):
    # Convenience wrapper for logging a status update both to stdout and to the DB.
    # Prints to console with timestamp, and if a JobStatusWriter is provided, 
    # also persists into JOB_RUNNER_LOG. This makes sure logs are visible 
    # both locally (container logs) and remotely (DB table).    
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{status or 'log'}] [{timestamp}] {message}", flush=True)

    if sql_status_writer:
        sql_status_writer.log(message, status=status)

 
 