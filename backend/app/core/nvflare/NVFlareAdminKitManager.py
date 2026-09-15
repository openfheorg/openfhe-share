import os
import tarfile
import tempfile
import shutil
import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
import pexpect

from app.core.EnvironmentManager import Environment, EnvironmentProvider


BASE_DIR = "/app/nvflare/admin"
STARTUP_SUBDIR = "startup"
ADMIN_SCRIPT = "fl_admin.sh"
ADMIN_NAME_ENV = "DUALITY_NVFLARE_ADMIN_NAME"


class NVFlareAdminKitManager:
    # Handles downloading/extracting NVFlare admin kit (local tar or S3 tar),
    # caches the last fingerprint, and runs commands through fl_admin.sh.

    def __init__(self):
        self.env = EnvironmentProvider.get_env()
        self.base = Path(BASE_DIR)

        self.tar_path = (os.getenv("DUALITY_ADMIN_TAR") or "").strip()
        if not self.tar_path:
            raise ValueError("DUALITY_ADMIN_TAR is not set")

        self.s3_client = None
        if self.env != Environment.LOCAL:
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            self.s3_client = boto3.client("s3", region_name=region)

        self.base.mkdir(parents=True, exist_ok=True)

        self._admin_home: Optional[Path] = None
        self._script_path: Optional[Path] = None
        self._last_token: Optional[str] = None

    def run(self, commands: List[str], timeout: int = 300) -> Tuple[int, str]:
        # Ensure kit is ready before running anything
        self._ensure_ready()

        child = pexpect.spawn(
            str(self._script_path),
            cwd=str(self._admin_home / STARTUP_SUBDIR),
            encoding="utf-8",
            timeout=timeout,
        )
        logs: List[str] = []

        prompt_regex = re.compile(r"\n?>\s*$")

        def expect_next() -> int:
            # 0: prompt, 1: username prompt, 2: EOF, 3: TIMEOUT
            return child.expect([prompt_regex, r"[Uu]ser\s*[Nn]ame.*:", pexpect.EOF, pexpect.TIMEOUT])

        def bail(reason: str) -> Tuple[int, str]:
            logs.append(child.before or "")
            logs.append(f"\n[fl_admin] Aborted: {reason}")
            try:
                child.close(force=True)
            except Exception:
                pass
            return 1, self._normalize_output("\n".join(filter(None, logs)))

        idx = expect_next()
        logs.append(child.before or "")

        if idx == 1:
            admin_name = (os.getenv(ADMIN_NAME_ENV) or "").strip()
            child.sendline(admin_name)
            idx = expect_next()
            logs.append(child.before or "")
        elif idx in (2, 3):
            return bail("console closed or timed out before first prompt")

        for cmd in commands:
            child.sendline(cmd)
            idx = expect_next()
            logs.append(child.before or "")
            if idx in (2, 3):
                return bail(f"console closed or timed out while running: {cmd}")

        child.sendline("bye")
        try:
            child.expect(pexpect.EOF)
        except Exception:
            pass
        logs.append(child.before or "")

        return (child.exitstatus or 0, self._normalize_output("\n".join(filter(None, logs))))

    def _ensure_ready(self) -> None:
        # Check whether tarball changed since last extraction, extract if needed
        token = self._current_token()
        token_file = self.base / ".etag"
        prior = token_file.read_text().strip() if token_file.exists() else ""

        need_extract = (token != prior)
        if need_extract:
            if self.env == Environment.LOCAL:
                self._extract_local(token)
            else:
                self._download_and_extract_s3(token)

        if not self._admin_home or not self._script_path or need_extract:
            admin_home = self._resolve_admin_home()
            if not admin_home:
                raise RuntimeError("startup/fl_admin.sh not found after extraction")

            script = admin_home / STARTUP_SUBDIR / ADMIN_SCRIPT
            if not script.exists():
                raise FileNotFoundError(f"{ADMIN_SCRIPT} not found at {script}")

            # Ensure the script is runnable even if the tar lost perms or had CRLF
            self._harden_script(script)

            self._admin_home = admin_home
            self._script_path = script
            self._last_token = token

    def _harden_script(self, script: Path) -> None:
        # Add execute bit
        try:
            script.chmod(script.stat().st_mode | 0o111)
        except Exception:
            pass
        # Normalize CRLF -> LF if needed
        try:
            b = script.read_bytes()
            if b"\r\n" in b:
                script.write_bytes(b.replace(b"\r\n", b"\n"))
        except Exception:
            pass

    def _current_token(self) -> str:
        # Fingerprint of the tarball: LOCAL uses size+mtime, non-local uses S3 ETag
        if self.env == Environment.LOCAL:
            p = Path(self.tar_path)
            if not p.exists():
                raise FileNotFoundError(self.tar_path)
            h = hashlib.sha256()
            st = p.stat()
            h.update(str(st.st_size).encode())
            h.update(str(int(st.st_mtime)).encode())
            return h.hexdigest()

        bucket, key = self._parse_s3_uri(self.tar_path)
        try:
            head = self.s3_client.head_object(Bucket=bucket, Key=key)
            return (head.get("ETag") or "").strip('"')
        except ClientError:
            return ""

    def _download_and_extract_s3(self, token: str) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            bucket, key = self._parse_s3_uri(self.tar_path)
            self.s3_client.download_file(bucket, key, str(tmp_path))
            self._clean_dir(self.base)
            self._extract_archive(tmp_path, self.base, gz=key.endswith(".tar.gz"))
            (self.base / ".etag").write_text(token or "")
        finally:
            tmp_path.unlink(missing_ok=True)

    def _extract_local(self, token: str) -> None:
        src = Path(self.tar_path)
        self._clean_dir(self.base)
        self._extract_archive(src, self.base, gz=str(src).endswith(".tar.gz"))
        (self.base / ".etag").write_text(token or "")

    def _extract_archive(self, archive_path: Path, target_dir: Path, gz: bool) -> None:
        mode = "r:gz" if gz else "r:"
        with tarfile.open(archive_path, mode) as tar:
            for member in tar.getmembers():
                dest = (target_dir / member.name).resolve()
                if not str(dest).startswith(str(target_dir.resolve())):
                    raise RuntimeError(f"refusing to extract outside target dir: {member.name}")
            tar.extractall(target_dir)

    def _resolve_admin_home(self) -> Optional[Path]:
        children = [p for p in self.base.iterdir() if p.is_dir()]
        for d in children:
            if (d / STARTUP_SUBDIR / ADMIN_SCRIPT).exists():
                return d
        return None

    def _clean_dir(self, root: Path) -> None:
        for entry in root.iterdir():
            if entry.name == ".etag":
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    def _parse_s3_uri(self, uri: str) -> Tuple[str, str]:
        if not uri.startswith("s3://"):
            raise ValueError("S3 URI must start with s3://")
        without = uri[5:]
        parts = without.split("/", 1)
        if len(parts) != 2:
            raise ValueError("S3 URI must look like s3://bucket/key")
        return parts[0], parts[1]

    @staticmethod
    def _normalize_output(s: str) -> str:
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        s = ansi.sub("", s)
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = "\n".join(line.rstrip() for line in s.split("\n"))
        return s.strip()
