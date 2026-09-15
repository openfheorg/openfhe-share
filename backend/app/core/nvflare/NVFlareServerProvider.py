'''
This module provides provisioning information for NVFlare workspaces.
It defines the NVFlareProvision dataclass for holding base, admin,
and server locations, and a provider that returns appropriate
instances depending on environment and function type.
'''

from dataclasses import dataclass
import os
from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.mysql.SupportedFunction import SupportedFunction

@dataclass
class NVFlareProvision:
    base_location: str
    admin_location: str
    server_location: str
    client_to_server_job_save_location: str

class NVFlareProvisionProvider:
    @staticmethod
    def get_nvflare_instance(env: Environment = None) -> NVFlareProvision:
        if env is None:
            env = EnvironmentProvider.get_env()

        if env == Environment.LOCAL:
            host = os.getenv("DUALITY_NVFLARE_HOST", "127.0.0.1")
            base = os.path.abspath(os.getenv("DUALITY_NVFLARE_WORKSPACE", "./nvflare_workspace"))
            job_save = os.getenv("DUALITY_NVFLARE_JOB_SAVE_LOCATION")
            if not job_save:
                job_save = os.path.join(base, "job-results")
            job_save = os.path.abspath(job_save)

            admin_location = os.path.join(base, "admin@share.local")
            server_location = os.path.join(base, host)

            return NVFlareProvision(
                base_location=base,
                admin_location=admin_location,
                server_location=server_location,
                client_to_server_job_save_location=job_save,
            )

        # For separating out by environment
        if env == Environment.DEV:
            base = "/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00"
            ec2 = "nvflare.example.org"
            return NVFlareProvision(
                base_location=base,
                admin_location=f"{base}/admin@share.local",
                server_location=f"{base}/{ec2}",
                # client_to_server_job_save_location=f"{base}/{ec2}/job-results",
                client_to_server_job_save_location=f"{base}/{"site3"}/job-results",

            )
