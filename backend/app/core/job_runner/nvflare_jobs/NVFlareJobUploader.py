#DEPRECATED CLASS


import json
import os
import re
import tempfile
import zipfile
import shutil
from pathlib import Path
from typing import List, Optional

from app.core.aws.ResourceConfigProvider import SSHSecret
from app.core.mysql.MySQLRetriever import MySQLRetriever
from app.core.mysql.managers.FiltersManager import FiltersManager
from app.core.nvflare.NVFlareServerProvider import NVFlareProvision
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider
import MySQLdb

from app.core.mysql.job_tracking.JobStatusWriter import JobRunnerStatus, JobStatusWriter
from app.core.ssh.SSHConnectionProvider import SSHConnectionProvider
from app.core.mysql.SupportedFunction import SupportedFunction

# Local base directory in container where NVFlare jobs live
LOCAL_NVFLARE_JOBS_DIR = os.path.join("app", "core", "job_runner", "nvflare_jobs")

# Where to stage local jobs for fl_admin submit_job (overridable)
LOCAL_JOB_ROOT = Path("/tmp/nvflare_jobs").resolve()


class NVFlareJobUploader:
    def __init__(
        self,
        function: SupportedFunction,
        ssh_provider: SSHConnectionProvider,
        status_writer: JobStatusWriter,
        nvflare_provision: NVFlareProvision,
        clients_list: str,
        filters_id: Optional[int] = None,
    ):
        # Needs an SSH provider and config so we can push files to EC2,
        # a status_writer for logging, the NVFlareProvision object so we know
        # where the admin startup dir lives, and an optional filters dict.
        # filters can be a filter_id, a full filter object, or even a JSON string.
        self.function = function
        self.ssh_provider = ssh_provider
        self.status_writer = status_writer
        self.nvflare_provision = nvflare_provision

        self.participating_clients = clients_list
        self.filters = None

        # If filters were requested by id, resolve them up front.
        if filters_id:
            mr = MySQLRetriever()
            self.filters = mr.get_single_filter(filters_id)
            mr.complete()

    # def _csv_decode(self, s: str) -> List[str]:
    #     out, cur, esc = [], [], False
    #     for ch in s or "":
    #         if esc:
    #             cur.append(ch)
    #             esc = False
    #         elif ch == "\\":
    #             esc = True
    #         elif ch == ",":
    #             out.append("".join(cur))
    #             cur = []
    #         else:
    #             cur.append(ch)
    #     out.append("".join(cur))
    #     return out

    # def _parse_clients(self, clients_csv: str) -> List[str]:
    #     if not clients_csv:
    #         return []
    #     return [c.strip() for c in self._csv_decode(clients_csv) if c.strip()]

    # def _materialize_metajson_payload(self, job_name: str, clients_csv: str):
    #     clients = self._parse_clients(clients_csv)
    #     return {
    #         "name": job_name.lower(),
    #         "resource_spec": {},
    #         "min_clients": max(1, len(clients)),
    #         "deploy_map": {
    #             "app_client": clients,
    #             "app_server": ["server"],
    #         },
    #         "job_name": job_name,
    #     }

    # def _read_text(self, path: str) -> str:
    #     with open(path, "r", encoding="utf-8") as f:
    #         return f.read()

    # def _strip_json_comments(self, s: str) -> str:
    #     s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    #     s = re.sub(r"(^|\s)//.*?$", r"\1", s, flags=re.MULTILINE)
    #     return s

    # def _load_json_lenient(self, s: str) -> dict:
    #     return json.loads(self._strip_json_comments(s))

    # def _dump_json(self, obj: dict) -> str:
    #     return json.dumps(obj, indent=2, ensure_ascii=False)

    # def _update_server_config_text(self, raw_text: str, client_count: int) -> Optional[str]:
    #     try:
    #         data = self._load_json_lenient(raw_text)
    #     except Exception:
    #         return None
    #     wf = data.get("workflows")
    #     if not isinstance(wf, list):
    #         return None
    #     updated = False
    #     for w in wf:
    #         args = w.get("args")
    #         if isinstance(args, dict):
    #             if args.get("min_clients") != client_count:
    #                 args["min_clients"] = client_count
    #                 updated = True
    #     if not updated:
    #         return None
    #     return self._dump_json(data)


    # def zip_job(self, job_name: str) -> str:
    #     job_path = os.path.join(LOCAL_NVFLARE_JOBS_DIR, job_name)
    #     if not os.path.exists(job_path):
    #         raise FileNotFoundError(f"Job folder does not exist: {job_path}")

    #     clients = self._parse_clients(self.participating_clients or "")
    #     client_count = max(1, len(clients))

    #     tmp_dir = tempfile.gettempdir()
    #     zip_path = os.path.join(tmp_dir, f"{job_name}.zip")

    #     server_cfg_rel = os.path.join("app_server", "config", "config_fed_server.json")
    #     server_cfg_abs = os.path.join(job_path, server_cfg_rel)
    #     server_cfg_updated_text = None
    #     if os.path.exists(server_cfg_abs):
    #         raw = self._read_text(server_cfg_abs)
    #         server_cfg_updated_text = self._update_server_config_text(raw, client_count)

    #     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    #         for root, _, files in os.walk(job_path):
    #             for file in files:
    #                 abs_path = os.path.join(root, file)
    #                 rel_path = os.path.relpath(abs_path, job_path)
    #                 if rel_path.replace("\\", "/") == server_cfg_rel.replace("\\", "/") and server_cfg_updated_text:
    #                     zf.writestr(server_cfg_rel, server_cfg_updated_text)
    #                 else:
    #                     zf.write(abs_path, rel_path)

    #         if self.filters is not None:
    #             filters_payload = self.filters if isinstance(self.filters, str) else json.dumps(self.filters, indent=2)
    #             for app_name in ("app_client", "app_server"):
    #                 filters_loc = os.path.join(app_name, "custom", "filters.json")
    #                 zf.writestr(filters_loc, filters_payload)

    #         if self.participating_clients is not None:
    #             meta_json_payload = self._materialize_metajson_payload(
    #                 job_name=job_name, clients_csv=self.participating_clients
    #             )
    #             meta_json_loc = os.path.join("meta.json")
    #             if isinstance(meta_json_payload, str):
    #                 zf.writestr(meta_json_loc, meta_json_payload)
    #             else:
    #                 zf.writestr(meta_json_loc, json.dumps(meta_json_payload, indent=2))

    #     return zip_path

    # def upload_and_unzip_job(self, local_zip_path: str) -> str:
    #     remote_zip = f"{self.nvflare_provision.final_job_location}/{os.path.basename(local_zip_path)}"
    #     remote_dir = remote_zip.rsplit(".", 1)[0]

    #     preclean_cmd = f"rm -f {remote_zip} && rm -rf {remote_dir} && mkdir -p {remote_dir}"
    #     code, out, err = self.ssh_provider.run(preclean_cmd)
    #     if code != 0:
    #         raise RuntimeError(f"Remote pre-clean failed: {err or out}")

    #     self.ssh_provider.upload(local_zip_path, remote_zip)

    #     unzip_cmd = f"unzip -q -o {remote_zip} -d {remote_dir}"
    #     code, out, err = self.ssh_provider.run(unzip_cmd)
    #     if code != 0:
    #         raise RuntimeError(f"Unzip failed: {err or out}")

    #     self.status_writer.log(
    #         "NVFlareJobUploader: Job successfully submitted to NVFlare server.",
    #         JobRunnerStatus.JOB_UPLOAD,
    #     )

    #     cleanup_cmd = f"rm -f {remote_zip}"
    #     self.ssh_provider.run(cleanup_cmd)

    #     return remote_dir


    # def _safe_clean_dir(self, path: Path):
    #     if path.exists():
    #         shutil.rmtree(path)
    #     path.mkdir(parents=True, exist_ok=True)

    # def _copytree(self, src: Path, dst: Path):
    #     for root, dirs, files in os.walk(src):
    #         rel = Path(root).relative_to(src)
    #         (dst / rel).mkdir(parents=True, exist_ok=True)
    #         for f in files:
    #             s = Path(root) / f
    #             d = (dst / rel / f)
    #             if d.suffix in (".pyc", ".pyo"):
    #                 continue
    #             shutil.copy2(s, d)

    # def _build_local_job_dir(self, job_name: str) -> Path:
    #     template = Path(LOCAL_NVFLARE_JOBS_DIR) / job_name
    #     if not template.exists():
    #         raise FileNotFoundError(f"Job template not found: {template}")

    #     job_dir = (LOCAL_JOB_ROOT / job_name).resolve()
    #     self._safe_clean_dir(job_dir)
    #     self._copytree(template, job_dir)

    #     clients = self._parse_clients(self.participating_clients or "")
    #     client_count = max(1, len(clients))

    #     server_cfg_rel = Path("app_server") / "config" / "config_fed_server.json"
    #     server_cfg = job_dir / server_cfg_rel
    #     if server_cfg.exists():
    #         try:
    #             raw = server_cfg.read_text(encoding="utf-8")
    #             patched = self._update_server_config_text(raw, client_count)
    #             if patched is not None:
    #                 server_cfg.write_text(patched, encoding="utf-8")
    #         except Exception:
    #             pass

    #     if self.filters is not None:
    #         filters_payload = self.filters if isinstance(self.filters, str) else json.dumps(self.filters, indent=2)
    #         for app_name in ("app_client", "app_server"):
    #             (job_dir / app_name / "custom").mkdir(parents=True, exist_ok=True)
    #             (job_dir / app_name / "custom" / "filters.json").write_text(filters_payload, encoding="utf-8")

    #     meta_payload = self._materialize_metajson_payload(job_name=job_name, clients_csv=self.participating_clients or "")
    #     (job_dir / "meta.json").write_text(
    #         meta_payload if isinstance(meta_payload, str) else json.dumps(meta_payload, indent=2),
    #         encoding="utf-8",
    #     )

    #     return job_dir


    # def send_job(self, job_name: str) -> str:
    #     """
    #     DEV/SSH: zip + upload + unzip on remote → returns remote_dir (remote path)
    #     LOCAL/ADMIN: materialize local job dir → returns remote_dir (but it's a local path)
    #     """
    #     # LOCAL/ADMIN mode if an admin kit is present/expected
    #     if os.getenv("DUALITY_ADMIN_TAR"):
    #         job_dir = self._build_local_job_dir(job_name.lower())
    #         final_job_destination = str(job_dir)   # keep the same variable name as before
    #         return final_job_destination

    #     # Legacy SSH path
    #     zip_path = self.zip_job(job_name.lower())
    #     final_job_destination = self.upload_and_unzip_job(zip_path)
    #     return final_job_destination
