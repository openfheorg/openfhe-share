import time
from typing import Dict, Any, List, Optional, Set

from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.job_runner.nvflare_jobs.NVFlareJobRunner import NVFlareJobRunner
from app.core.job_runner.nvflare_jobs.NVFlareJobStager import NVFlareJobStager
from app.core.mysql.managers.ParticipationManager import Confirmation, ParticipationManager
from app.core.mysql.SupportedFunction import SupportedFunction
from app.core.mysql.managers.NVFlareJobsManager import NVFlareJobsManager, NVFlareStatus
from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.mysql.managers.ThresholdManager import Threshold
from app.core.nvflare.NVFlareClientSnapshot import NVFlareClientSnapshot
from app.core.nvflare.NVFlareServerProvider import NVFlareProvisionProvider
from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider


class NVFlareParticipationJobTask:

    def __init__(
        self,
        project_id,
        datasource_group_id: Optional[int],
        functions_map: Dict[str, Any],
        filters_id,
        nvflare_provision: NVFlareProvisionProvider,
        nvflare_jobs_manager: NVFlareJobsManager,
        status_writer: JobStatusWriter,
        threshold: Optional[Threshold],
        timeout_in_seconds: int = 900,
        nvflare_job_internal_id = None,
        username: Optional[str] = None,
        non_contributing_clients: Optional[List[str]] = None,
        exclude_analyzing_clients: Optional[List[str]] = None
    ):
        self.project_id = project_id
        self.datasource_group_id = datasource_group_id
        self.status_writer = status_writer
        self.functions_map = functions_map
        self.filters_id = filters_id
        self.nvflare_provision = nvflare_provision
        self.nvflare_jobs_manager = nvflare_jobs_manager
        self.timeout_in_seconds = timeout_in_seconds
        self.env = None
        self.nvflare_job_internal_id = nvflare_job_internal_id
        self.threshold = threshold
        self.username = username
        self.non_contributing_clients = self._normalize_client_name_set(non_contributing_clients)
        self.exclude_analyzing_clients = self._normalize_client_name_set(exclude_analyzing_clients)
        self.excluded_clients = self.non_contributing_clients & self.exclude_analyzing_clients

    def _normalize_client_name_set(self, value: Optional[List[str]]) -> Set[str]:
        if not isinstance(value, list):
            return set()
        return {str(client_name).strip() for client_name in value if str(client_name).strip()}

    def _client_name_set_to_csv(self, value: Set[str]) -> str:
        return ",".join(sorted(value))

    def _filter_clients_snapshot(self, clients_snapshot: list[dict]) -> list[dict]:
        filtered_snapshot: list[dict] = []
        for client in clients_snapshot or []:
            client_name = str(client.get("client_name") or client.get("name") or "").strip()
            if client_name and client_name in self.excluded_clients:
                continue
            filtered_snapshot.append(client)
        return filtered_snapshot

    def _online_client_names_from_snapshot(self, clients_snapshot: list[dict]) -> Set[str]:
        client_names: Set[str] = set()
        for client in clients_snapshot or []:
            client_name = str(client.get("client_name") or client.get("name") or "").strip()
            last_connect_time = client.get("last_connect_time", client.get("last_online", client.get("lastConnect")))
            if client_name and last_connect_time and str(last_connect_time).strip() != "0":
                client_names.add(client_name)
        return client_names

    def _record_requested_participation_roles(
        self,
        participation_manager: ParticipationManager,
        clients_snapshot: list[dict],
    ) -> None:
        client_names = self._online_client_names_from_snapshot(clients_snapshot)
        existing_by_client = {
            row["client_name"]: row
            for row in participation_manager.list_client_participation_status(
                functions=self.functions_map,
                filter_id=self.filters_id,
                confirmation=None,
                clients_snapshot=clients_snapshot,
                threshold=self.threshold,
            )
        }

        for client_name in sorted(client_names):
            contributing_party = client_name not in self.non_contributing_clients
            analyzing_party = client_name not in self.exclude_analyzing_clients
            existing = existing_by_client.get(client_name)

            if existing:
                participation_manager.record_participation(
                    client_name=client_name,
                    filter_id=self.filters_id,
                    functions_map=self.functions_map,
                    confirmation=Confirmation(existing["confirmation"]),
                    threshold=self.threshold,
                    contributing_party=contributing_party,
                    analyzing_party=analyzing_party,
                )
                continue

            participation_manager.record_pending_participation(
                client_name=client_name,
                filter_id=self.filters_id,
                functions_map=self.functions_map,
                contributing_party=contributing_party,
                analyzing_party=analyzing_party,
                threshold=self.threshold,
            )

    def _pending_clients_csv(
        self,
        participation_manager: ParticipationManager,
        clients_snapshot: list[dict],
    ) -> str:
        rows = participation_manager.list_client_participation_status(
            functions=self.functions_map,
            filter_id=self.filters_id,
            confirmation=Confirmation.PENDING,
            clients_snapshot=clients_snapshot,
            threshold=self.threshold,
        )
        return self._client_name_set_to_csv({row["client_name"] for row in rows})

    def get_participation_client_list(self) -> str:
        """
        Orchestrates the NVFlare participation job flow:
          Phase 1: Get list of clients without participation (broadcast target).
          Phase 2: If all clients already responded, skip broadcast.
          Phase 3: Establish SSH to NVFlare server for connectivity check.
          Phase 4: Upload the packaged participation job.
          Phase 5: Submit job through NVFlare admin interface.
          Phase 6: Monitor MySQL until deadline for responses.
          Phase 7: Return final list of ACCEPT clients only.
        """

        function_names = ", ".join(sorted(self.functions_map))

        clients_snapshot = NVFlareClientSnapshot().get_clients()
        clients_snapshot = self._filter_clients_snapshot(clients_snapshot)

        participation_manager = ParticipationManager()
        self.status_writer.log(
            f"NVFlareParticipationJobTask: Participation job initializing for {function_names}",
            JobRunnerStatus.PARTICIPATION_INITIAL_CHECK
        )

        if self.username:
            user_client_names = participation_manager.get_client_names_for_username(self.username)
            skipped_client_names = sorted(user_client_names & self.excluded_clients)

            if skipped_client_names:
                self.status_writer.log(
                    f"NVFlareParticipationJobTask: Submitting user {self.username} is mapped to excluded client(s): {', '.join(skipped_client_names)}.",
                    JobRunnerStatus.PARTICIPATION_INITIAL_CHECK
                )
            else:
                auto_accepted_client = participation_manager.auto_accept_participation_for_username(
                    username=self.username,
                    filter_id=self.filters_id,
                    functions_map=self.functions_map,
                    threshold=self.threshold
                )

                if auto_accepted_client:
                    self.status_writer.log(
                        f"NVFlareParticipationJobTask: Auto-accepted participation for submitting user {self.username} on client {auto_accepted_client}.",
                        JobRunnerStatus.PARTICIPATION_INITIAL_CHECK
                    )
                else:
                    self.status_writer.log(
                        f"NVFlareParticipationJobTask: No auto-accept client mapping found for submitting user {self.username}.",
                        JobRunnerStatus.PARTICIPATION_INITIAL_CHECK
                    )

        self._record_requested_participation_roles(participation_manager, clients_snapshot)

        broadcast_clients_list = self._pending_clients_csv(participation_manager, clients_snapshot)

        if len(broadcast_clients_list) == 0:
            return self._accepted_clients(participation_manager, clients_snapshot, self.functions_map, self.threshold)

        # At least one client has not responded yet → need to broadcast.
        self.status_writer.log(
            f"NVFlareParticipationJobTask: Participation confirmation required from: {broadcast_clients_list}, beginning job...",
            JobRunnerStatus.ESTABLISHING_SECURE_CONNECTION
        )

        # Stage 2: (non-local) Establish SSH connection to NVFlare server to confirm connectivity.
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
                return ""


        # Stage 3: Upload packaged job to NVFlare server.
        self.nvflare_jobs_manager.set_nvflare_job_status(NVFlareStatus.STAGING)
        self.status_writer.log(
            f"NVFlareParticipationJobTask: Packaging and submitting participation job to NVFlare server for NVFlare job {self.nvflare_job_internal_id}...",
            JobRunnerStatus.JOB_DEFINING
        )

        job_submitter = NVFlareJobStager(self.project_id,
            functions_map=self.functions_map,
            status_writer=self.status_writer,
            clients_list=broadcast_clients_list,
            filters_id=self.filters_id,
            job_template_name=SupportedFunction.PARTICIPATION_CONFIRMATION.lower(),
            threshold=self.threshold,
            datasource_group_id = self.datasource_group_id
        )
        final_job_path = job_submitter.stage_job()
        self.nvflare_jobs_manager.set_nvflare_job_path(final_job_path)

        # Stage 4: Submit job via NVFlare’s admin interface.
        self.status_writer.log(
            "NVFlareParticipationJobTask: Submitting job to server",
            JobRunnerStatus.JOB_BROADCAST
        )
        runner = NVFlareJobRunner(
            self.nvflare_provision,
            self.status_writer,
            final_job_path=final_job_path
        )
        nvflare_job_generated_id, nvflare_output_path = runner.run_job()
        self.nvflare_jobs_manager.set_nvflare_job_status(NVFlareStatus.PROCESSING)


        # Stage 5: Monitor participation responses until deadline using our mysql table
        poll_interval = 5
        deadline = time.time() + int(self.timeout_in_seconds or 900)

        while True:
            missing_csv = self._pending_clients_csv(participation_manager, clients_snapshot)
            remaining = int(max(0, deadline - time.time()))
            missing_csv = (missing_csv or "").strip()

            if missing_csv and remaining > 0:
                self.status_writer.log(
                    f"NVFlareParticipationJobTask: Participation unconfirmed for: {missing_csv}.  {remaining} seconds left in response window.",
                    JobRunnerStatus.PARTICIPATION_MONITORING
                )

            if not missing_csv or remaining <= 0:
                break

            time.sleep(poll_interval)

        self.status_writer.log(
            "NVFlareParticipationJobTask: Participation step finished. Processing responses.",
            JobRunnerStatus.PARTICIPATION_ESTABLISHED
        )
        # Stage 7: Return only ACCEPTED clients for downstream job construction.
        return self._accepted_clients(participation_manager, clients_snapshot, self.functions_map, self.threshold)

 
    

    def _accepted_clients(
        self,
        participation_manager: ParticipationManager,
        clients_snapshot,
        normalized_functions: Dict[str, Dict[str, str]],
        threshold
    ) -> str:
        ret_client_list = participation_manager.list_clients_with_accepted_participation_csv(
            normalized_functions, self.filters_id, clients_snapshot, threshold
        )
        if len(ret_client_list) == 0:
            self.status_writer.log(
                "NVFlareParticipationJobTask: No client participation list established.",
                JobRunnerStatus.PARTICIPATION_EMPTY
            )
            return ""
        return ret_client_list
