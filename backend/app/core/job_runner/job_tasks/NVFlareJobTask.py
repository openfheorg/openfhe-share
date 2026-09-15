'''
"JobTask" style class, used to execute a specific function in the system with various arguments passed in. 
It ties together filters, NVFlare job creation, SSH connectivity, upload, execution, and monitoring 
into one end-to-end workflow.
'''

from typing import Any, Dict, List, Optional
from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.job_runner.nvflare_jobs.NVFlareJobMonitor import NVFlareJobMonitor
from app.core.job_runner.nvflare_jobs.NVFlareJobRunner import NVFlareJobRunner
from app.core.job_runner.nvflare_jobs.NVFlareJobStager import NVFlareJobStager
from app.core.mysql.managers.FiltersManager import FiltersManager
from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.managers.NVFlareJobsManager import FAILURE_JOB_RUNNER_STATUSES, NVFlareJobsManager, NVFlareStatus
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.mysql.managers.ThresholdManager import Threshold
from app.core.nvflare.NVFlareServerProvider import NVFlareProvisionProvider
from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider
from app.core.job_runner.job_tasks.NVFlareParticipationJobTask import NVFlareParticipationJobTask
from app.core.job_runner.job_tasks.JobCompletenessGate import (
    PARTIAL_STATUS,
    collect_produced_workflows,
    group_bindings_by_function,
    missing_workflow_results,
)

# The status NVFlare reports for a run that reached the end of its workflow list.
COMPLETED_STATUS = "FINISHED:COMPLETED"


class NVFlareJobTask:

    def __init__(self, 
                 project_id, 
                 datasource_group_id: Optional[int],
                 filters, 
                 status_writer: JobStatusWriter, 
                 functions_map: Dict[str, Dict[str, str]], 
                 threshold: Optional[Threshold],
                 username: Optional[str] = None,
                 workflow_group_data: Optional[Dict[str, Any]] = None,
                 non_contributing_clients: Optional[List[str]] = None,
                 exclude_analyzing_clients: Optional[List[str]] = None):
        # Constructor just wires in a JobStatusWriter so we can stream logs and updates 
        # as the job moves through different stages.        
        self.project_id = project_id
        self.datasource_group_id = datasource_group_id
        self.status_writer = status_writer
        self.functions_map = functions_map
        self.filters = filters
        self.threshold = threshold
        self.username = username
        self.workflow_group_data = workflow_group_data
        self.non_contributing_clients = non_contributing_clients or []
        self.exclude_analyzing_clients = exclude_analyzing_clients or []

    def run_nvflare_job(self):
        function_names = ", ".join(sorted(self.functions_map))
        # Kicks off a job from start to finish. 
        # Think of it as an orchestrator: it validates filters, records the job, 
        # uploads to NVFlare, runs it remotely, and then monitors until completion.

        # Stage 1: Process incoming filters and save them in MySQL if new. 
        # FiltersManager handles deduplication so we don’t store the same set twice.        
        self.status_writer.log(f"NVFlareJobTask: Job initiated for {function_names}", JobRunnerStatus.PROCESSING)
        
        filters_manager = FiltersManager(
            project_id=self.project_id,
            filters=self.filters,
            status_writer=self.status_writer
        )

        self.filters_id = filters_manager.save_or_get_filter_id()
        filters_manager.complete()
        
        # Stage 2: (non-local) Establish an SSH connection to the NVFlare server. 
        self.env = EnvironmentProvider.get_env()
        if self.env != Environment.LOCAL:
            self.status_writer.log("NVFlareJobTask: Establishing secure connection to NVFlare server...", JobRunnerStatus.ESTABLISHING_SECURE_CONNECTION)
            try:
                
                ssh_provider = SSHConnectionProvider.get_instance()

                code, out, err = ssh_provider.run("hostname && uptime")
                if code == 0:
                    self.status_writer.log("NVFlareJobTask: Secure connection verified to NVFlare server.", JobRunnerStatus.SECURE_CONNECTION_ESTABLISHED)
                else:
                    self.status_writer.log(f"NVFlareJobTask: Connection encountered unexpected response ({code}). Error: {err.strip()}", JobRunnerStatus.PROCESSING)

            except Exception as e:
                self.status_writer.log(f"NVFlareJobTask: Secure connection to NVFlare server failed: {e}", JobRunnerStatus.FAILURE)


        nvflare_provision = NVFlareProvisionProvider().get_nvflare_instance()

        # Stage 3: Initialize a new job record in NVFlareJobsManager. 
        # This creates an internal DB entry so we can track NVFlare’s assigned ID 
        # and any output paths that come back later.
        nvflare_jobs_manager = NVFlareJobsManager(status_writer = self.status_writer, project_id=self.project_id)


        self.nvflare_job_internal_id = nvflare_jobs_manager.establish_job_entry_id(
            filter_id=self.filters_id,
            functions_map=self.functions_map,
            threshold=self.threshold,
            non_contributing_clients=self.non_contributing_clients,
            exclude_analyzing_clients=self.exclude_analyzing_clients,
        )
        nvflare_jobs_manager.log_job_run_context(
            datasource_group_id=self.datasource_group_id,
            workflow_group_data=self.workflow_group_data,
        )
        
        

        # CONFIRM PARTICIPATION:
        participating_clients = NVFlareParticipationJobTask(
            project_id=self.project_id,
            datasource_group_id = self.datasource_group_id,
            functions_map = self.functions_map, 
            filters_id=self.filters_id, 
            nvflare_provision=nvflare_provision,
            nvflare_jobs_manager=nvflare_jobs_manager, 
            status_writer=self.status_writer, 
            timeout_in_seconds=900,
            nvflare_job_internal_id=self.nvflare_job_internal_id,
            threshold=self.threshold,
            username=self.username,
            non_contributing_clients=self.non_contributing_clients,
            exclude_analyzing_clients=self.exclude_analyzing_clients
            ).get_participation_client_list()
        
        print (f"NVFlareJobTask: participating_clients = {participating_clients}", flush=True)
        print(
            f"NVFlareJobTask: participation settings: "
            f"non_contributing_clients={self.non_contributing_clients}, "
            f"exclude_analyzing_clients={self.exclude_analyzing_clients}",
            flush=True,
        )

        if participating_clients is None or len(participating_clients) == 0:
            self.status_writer.log("NVFlareJobTask: No participating clients found for this job!", JobRunnerStatus.FAILURE)
            return


        # Stage 4: use submit_job to send our job to the nvflare server.
        # submit_job through fl_admin.sh will send the job data to the server via secure TLS connection
        nvflare_jobs_manager.set_nvflare_job_status(NVFlareStatus.STAGING)
        self.status_writer.log(f"NVFlareJobTask: Begin staging of {function_names} job", JobRunnerStatus.JOB_DEFINING)
          
            
        job_submitter = NVFlareJobStager(
            project_id=self.project_id,
            functions_map = self.functions_map, 
            status_writer = self.status_writer, 
            clients_list=participating_clients, 
            filters_id=self.filters_id,
            nvflare_jobs_manager=nvflare_jobs_manager,
            threshold=self.threshold,
            datasource_group_id = self.datasource_group_id,
            workflow_group_data = self.workflow_group_data,
            non_contributing_clients = self.non_contributing_clients,
            exclude_analyzing_clients = self.exclude_analyzing_clients)
        final_job_path = job_submitter.stage_job()
        nvflare_jobs_manager.set_nvflare_job_path(final_job_path)
        

        # Stage 5: Submit the job through NVFlare’s admin interface. 
        # NVFlareJobRunner handles calling fl_admin.sh with submit_job. 
        # NVFlare itself generates a new job ID and output path, 
        # which we immediately store back in NVFlareJobsManager.
        self.status_writer.log("NVFlareJobTask: Submitting job to server", JobRunnerStatus.JOB_BROADCAST)
        runner = NVFlareJobRunner(nvflare_provision, 
                                  self.status_writer,
                                  final_job_path=final_job_path)
        
        # From here on out we don't manually set status here. Client emit progress will update status with each call

        # This id was generated by the nvflare server, and output path determined by our function. Update our internal tracker:
        nvflare_job_generated_id, nvflare_output_path = runner.run_job()
        nvflare_jobs_manager.set_nvflare_assigned_id(nvflare_job_generated_id)
        nvflare_jobs_manager.set_nvflare_output_path(nvflare_output_path)    


        # Stage 6: Monitor the job on the NVFlare server. 
        # NVFlareJobMonitor polls for updates until we see a terminal state 
        # (COMPLETED, FAILED, CANCELLED) or a timeout hits. 
        # This keeps status flowing back to the UI in near real time.
        nvflare_job_monitor = NVFlareJobMonitor( 
            nvflare_jobs_manager,
            nvflare_job_generated_id,
            self.status_writer)
        
        final_nvflare_server_provided_status = nvflare_job_monitor.wait_for_completion(poll_interval=10, timeout=600)

        # A COMPLETED status only means the server runner reached the end of its workflow list,
        # not that every requested computation produced a result: a run whose server process
        # dies part way through still reports COMPLETED, and the results page then silently
        # omits the computations that never ran. Verify before reporting success.
        final_nvflare_server_provided_status = self._verify_run_completeness(
            nvflare_jobs_manager,
            nvflare_job_generated_id,
            final_nvflare_server_provided_status,
        )

        # Stage 7: Wrap things up.
        # We log the final server-provided status, call NVFlareJobsManager complete, 
        # and the task ends. At this point the job’s results should be retrievable 
        # from wherever NVFlare wrote them out.
        self.status_writer.log(f"NVFlareJobTask: job completed with a status of {final_nvflare_server_provided_status}.",
                               JobRunnerStatus.FAILURE if final_nvflare_server_provided_status in FAILURE_JOB_RUNNER_STATUSES else JobRunnerStatus.DONE)

        nvflare_jobs_manager.complete()

    def _verify_run_completeness(
        self,
        nvflare_jobs_manager: NVFlareJobsManager,
        nvflare_job_generated_id: str,
        final_status: str,
    ) -> str:
        """Downgrade a COMPLETED run to PARTIAL when a bound workflow produced no results.

        Returns the status to report. Only ever acts on COMPLETED: a run that already failed,
        aborted, or was overridden to a job-runner failure status (e.g. a threshold-not-met condition)
        keeps the status it has. Any error in the check itself is logged and ignored -- a
        verification bug must not fail an otherwise good run.
        """
        if str(final_status or "").strip().upper() != COMPLETED_STATUS:
            return final_status

        try:
            expected = group_bindings_by_function(nvflare_jobs_manager.get_workflow_bindings())
            if not expected:
                # Nothing was bound (older job, or a template with no function configs);
                # there is nothing to verify against.
                return final_status

            produced = collect_produced_workflows(nvflare_job_generated_id, expected.keys())
            gaps = missing_workflow_results(expected, produced)
            if not gaps:
                return final_status

            missing_text = ", ".join(f"{function}/{workflow}" for function, workflow in gaps)
            expected_count = sum(len(ids) for ids in expected.values())
            message = (
                f"NVFlareJobTask: job reported {final_status} but {len(gaps)} of {expected_count} "
                f"requested computation(s) produced no results: {missing_text}. "
                "Reporting the run as incomplete."
            )
            self.status_writer.log(message, JobRunnerStatus.ANALYSIS_FAILURE)
            return nvflare_jobs_manager.set_nvflare_job_status(PARTIAL_STATUS)
        except Exception as e:
            self.status_writer.log(
                f"NVFlareJobTask: could not verify run completeness ({e}); "
                f"leaving the status as {final_status}.",
                JobRunnerStatus.WARNING,
            )
            return final_status

 