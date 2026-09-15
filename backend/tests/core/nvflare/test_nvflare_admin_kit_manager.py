import io
import os
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.EnvironmentManager import Environment
from app.core.nvflare.NVFlareAdminKitManager import NVFlareAdminKitManager


def _manager_without_init(tmp_path: Path) -> NVFlareAdminKitManager:
    manager = object.__new__(NVFlareAdminKitManager)
    manager.env = Environment.LOCAL
    manager.base = tmp_path
    manager.tar_path = ""
    manager.s3_client = None
    manager._admin_home = None
    manager._script_path = None
    manager._last_token = None
    return manager


def test_parse_s3_uri():
    manager = _manager_without_init(Path("/tmp"))
    assert manager._parse_s3_uri("s3://bucket/path/kit.tar.gz") == (
        "bucket",
        "path/kit.tar.gz",
    )


@pytest.mark.parametrize("value", ["bucket/key", "s3://bucket"])
def test_parse_s3_uri_rejects_invalid_values(value):
    manager = _manager_without_init(Path("/tmp"))
    with pytest.raises(ValueError):
        manager._parse_s3_uri(value)


def test_normalize_output_removes_ansi_crlf_and_trailing_space():
    value = "\x1b[31mhello\x1b[0m  \r\nworld \r"
    assert NVFlareAdminKitManager._normalize_output(value) == "hello\nworld"


def test_harden_script_adds_execute_bits_and_normalizes_crlf(tmp_path):
    script = tmp_path / "fl_admin.sh"
    script.write_bytes(b"#!/bin/bash\r\necho ok\r\n")
    script.chmod(0o644)
    manager = _manager_without_init(tmp_path)

    # Native Windows filesystems do not expose Unix execute bits. Verify the
    # chmod request itself, while separately checking the portable CRLF fix.
    with patch.object(type(script), "chmod", autospec=True) as chmod_mock:
        manager._harden_script(script)

    assert script.read_bytes() == b"#!/bin/bash\necho ok\n"
    chmod_mock.assert_called_once()
    requested_mode = chmod_mock.call_args.args[1]
    assert requested_mode & 0o111 == 0o111


def test_extract_archive_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        data = b"escape"
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    manager = _manager_without_init(tmp_path / "target")
    manager.base.mkdir()

    with pytest.raises(RuntimeError, match="outside target dir"):
        manager._extract_archive(archive_path, manager.base, gz=True)


def test_resolve_admin_home_finds_startup_script(tmp_path):
    home = tmp_path / "admin@example"
    startup = home / "startup"
    startup.mkdir(parents=True)
    (startup / "fl_admin.sh").write_text("#!/bin/bash\n")
    manager = _manager_without_init(tmp_path)

    assert manager._resolve_admin_home() == home


def test_clean_dir_keeps_etag(tmp_path):
    (tmp_path / ".etag").write_text("token")
    (tmp_path / "file").write_text("x")
    (tmp_path / "folder").mkdir()
    manager = _manager_without_init(tmp_path)

    manager._clean_dir(tmp_path)

    assert (tmp_path / ".etag").exists()
    assert not (tmp_path / "file").exists()
    assert not (tmp_path / "folder").exists()
