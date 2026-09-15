"""
JobRunnerService acts as a regulator for running tasks. The queue takes in the requested task,
and executes them sequentially (no parallel running tasks). The service is responsible for
setting up a status writer for the task, assigning a job id to the task, and executing the
task on its own running thread.
"""
import threading
import queue
import traceback
import uuid
from typing import Any, Dict, List, Optional

from app.core.job_runner.job_tasks.NVFlareJobTask import NVFlareJobTask
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.mysql.managers.ThresholdManager import Threshold


class JobRunnerService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # Creates the queue, a registry for active jobs, and starts up
        # the background worker thread that actually consumes jobs one at a time.
        # Everything runs serially on that worker thread to keep things simple
        # and avoid concurrency headaches.
        self.task_queue = queue.Queue()
        self.job_registry: Dict[str, JobStatusWriter] = {}
        self.thread = threading.Thread(target=self._worker, daemon=True, name="JobRunnerService")
        self.thread.start()
        print("JobRunnerService started...")

    @staticmethod
    def get_instance():
        # Singleton getter. Ensures we only ever have one JobRunnerService
        # running in the process. Uses a double-checked lock for thread safety.
        if JobRunnerService._instance is None:
            with JobRunnerService._lock:
                if JobRunnerService._instance is None:
                    JobRunnerService._instance = JobRunnerService()
        return JobRunnerService._instance

    def request_job_run(
        self,
        project_id,
        functions_map: Dict[str, Dict[str, str]],
        filters,
        threshold: Optional[Threshold] = None,
        username: Optional[str] = None,
        datasource_group_id: Optional[int] = None,
        workflow_group_data: Optional[Dict[str, Any]] = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ) -> str:
        """
        Queues a job with a map of function_id -> { args }, the provided filters, and
        an optional threshold; returns job_id.

        Notes:
        - Endpoint guarantees function IDs are UPPERCASE and defaults are applied.
        - This layer assumes functions_map is a non-empty dict and forwards it to the worker.
        """
        if not isinstance(functions_map, dict) or not functions_map:
            raise ValueError("functions_map must be a non-empty object mapping function_id -> { args }")

        return self._make_request(
            project_id,
            filters,
            functions_map,
            threshold,
            username,
            datasource_group_id,
            workflow_group_data,
            non_contributing_clients,
            exclude_analyzing_clients,
        )

    def get_status_writer(self, job_id: str) -> JobStatusWriter | None:
        # Lookup helper. Given a job_id, return its JobStatusWriter so
        # external code can fetch current status/logs.
        return self.job_registry.get(job_id)

    def _make_request(
        self,
        project_id,
        filters,
        functions_map: Dict[str, Dict[str, str]],
        threshold: Optional[Threshold] = None,
        username: Optional[str] = None,
        datasource_group_id: Optional[int] = None,
        workflow_group_data: Optional[Dict[str, Any]] = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ) -> str:
        """
        Creates a new job_id, wires up a JobStatusWriter, logs the initial QUEUED status,
        puts the job into the queue, and returns the job_id to the caller.
        This is the central entry point for scheduling a job.
        """
        job_id = str(uuid.uuid4())
        status_writer = JobStatusWriter(job_id)

        # Default status of QUEUED
        status_writer.log("Job queued.", status=JobRunnerStatus.QUEUED)
        self.job_registry[job_id] = status_writer

        # Add to queue the functions_map, our instance of status_writer, and any input needed for this run (filters for instance)
        self._add_to_queue(
            project_id,
            functions_map,
            status_writer,
            filters,
            threshold,
            username,
            datasource_group_id,
            workflow_group_data,
            non_contributing_clients,
            exclude_analyzing_clients,
        )

        return job_id

    def _add_to_queue(
        self,
        project_id,
        functions_map: Dict[str, Dict[str, str]],
        status_writer: JobStatusWriter,
        filters,
        threshold: Optional[Threshold] = None,
        username: Optional[str] = None,
        datasource_group_id: Optional[int] = None,
        workflow_group_data: Optional[Dict[str, Any]] = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None,
    ):
        # Internal helper to push a job into the queue with its function configuration map.
        if not isinstance(functions_map, dict) or not functions_map:
            raise TypeError("functions_map must be a non-empty dict")

        self.task_queue.put((
            project_id,
            functions_map,
            status_writer,
            filters,
            threshold,
            username,
            datasource_group_id,
            workflow_group_data,
            non_contributing_clients or [],
            exclude_analyzing_clients or [],
        ))

    def _worker(self):
        # The background worker thread. Runs forever, pulling jobs off the queue one by one.
        # Logs that the job started, then dispatches to the appropriate task class.
        # Any exceptions are caught, stack trace printed, and the job logged as FAILURE.
        # Finally, marks the task as done so the queue stays healthy.
        while True:
            (
                project_id,
                functions_map,
                status_writer,
                filters,
                threshold,
                username,
                datasource_group_id,
                workflow_group_data,
                non_contributing_clients,
                exclude_analyzing_clients,
            ) = self.task_queue.get()
            try:
                NVFlareJobTask(
                    project_id=project_id,
                    filters=filters,
                    status_writer=status_writer,
                    functions_map=functions_map,
                    threshold=threshold,
                    username=username,
                    datasource_group_id=datasource_group_id,
                    workflow_group_data=workflow_group_data,
                    non_contributing_clients=non_contributing_clients,
                    exclude_analyzing_clients=exclude_analyzing_clients,
                ).run_nvflare_job()
            except Exception as e:
                tb = traceback.format_exc()
                print(tb, flush=True)
                status_writer.log(f"JobRunnerService exception: {e}\n{tb}", status=JobRunnerStatus.FAILURE)
            finally:
                self.task_queue.task_done()