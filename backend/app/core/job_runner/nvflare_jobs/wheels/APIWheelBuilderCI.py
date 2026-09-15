import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from setuptools import find_packages

IGNORE_PATTERNS = {"__pycache__", ".pyc", ".pyo", ".orig"}


class APIWheelBuilderCI:
    DIST_NAME = "duality_nvflare_lib"
    DEFAULT_VERSION = "0+phase1.snapshot"

    INSTALL_REQUIRES = [
        "numpy==2.2.6",
        "python-dateutil>=2.8.2",
        "pandas==2.3.3",
        "scipy==1.15.3",
        "requests>=2.32.5,<=2.33.1",
        "nvflare==2.7.2",
        "openfhe>=1.5",
        "cryptography>=43.0.3",
        "liboqs-python>=0.14.0",
        "boto3==1.41.1",
        "matplotlib==3.10.7",
        "statsmodels==0.14.4",
    ]

    PACKAGE_DATA = {"": ["*.json", "*.yml", "*.yaml"]}

    REQUIRED_RELATIVE_PATHS = [
        "apis",
        "apis/fhir",
        "apis/fhir/config",
        "workflows",
    ]

    def __init__(self, root: Path, out_dir: Path, version: str):
        self.root = root.resolve()
        self.out_dir = out_dir.resolve()
        self.version = self._normalize_version(version)
        self.apis_src = self.root / "apis"
        self.workflows_src = self.root / "workflows"

    @classmethod
    def from_args(cls, args):
        script_dir = Path(__file__).resolve().parent
        default_root = script_dir.parent
        root = Path(args.root).resolve() if args.root else default_root
        out_dir = Path(args.out_dir).resolve() if args.out_dir else script_dir
        version = args.version or cls.DEFAULT_VERSION
        return cls(root=root, out_dir=out_dir, version=version)

    def build(self) -> int:
        self._validate_required_paths()
        self._clean_existing_wheels()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pkg_apis = tmp_path / "duality_nvflare_apis"
            pkg_workflows = tmp_path / "duality_nvflare_workflows"

            print(f"[INFO] copying {self.apis_src} -> {pkg_apis}")
            self._copy_tree(self.apis_src, pkg_apis)

            print(f"[INFO] copying {self.workflows_src} -> {pkg_workflows}")
            self._copy_tree(self.workflows_src, pkg_workflows)

            self._verify_staged_package(tmp_path, pkg_apis / "fhir")
            self._verify_staged_package(tmp_path, pkg_apis / "fhir" / "config")
            self._log_find_packages(tmp_path)
            self._write_setup_py(tmp_path)

            print(f"[INFO] building {self.DIST_NAME}-{self.version}")
            subprocess.run(
                [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(self.out_dir)],
                cwd=tmp_path,
                check=True,
            )

        self._log_built_artifacts()
        return 0

    def _validate_required_paths(self):
        for relative_path in self.REQUIRED_RELATIVE_PATHS:
            required = self.root / relative_path
            if not required.exists():
                raise FileNotFoundError(f"missing required path: {required}")

    def _clean_existing_wheels(self):
        for existing in self.out_dir.glob(f"{self.DIST_NAME}-*.whl"):
            try:
                existing.unlink()
                print(f"[INFO] removed old wheel: {existing.name}")
            except OSError as exc:
                print(f"[WARN] could not remove {existing}: {exc}")

    def _copy_tree(self, src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        self._stamp_init(dst)

        for item in src.rglob("*"):
            if self._should_ignore(item):
                continue

            relative = item.relative_to(src)
            target = dst / relative

            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                self._stamp_init(target)
                print(f"[INFO]   dir  : {target.relative_to(dst.parent)}")
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    def _verify_staged_package(self, tmp_path: Path, expected: Path):
        if not expected.is_dir():
            raise FileNotFoundError(f"expected sub-package missing after copy: {expected}")
        print(f"[INFO] verified: {expected.relative_to(tmp_path)}")

    def _log_find_packages(self, tmp_path: Path):
        found = find_packages(where=str(tmp_path))
        print(f"[INFO] packages to be included in wheel: {sorted(found)}")

    def _write_setup_py(self, tmp_path: Path):
        install_requires = ",\n".join(f"    {dependency!r}" for dependency in self.INSTALL_REQUIRES)
        setup_contents = (
            "from setuptools import setup, find_packages\n"
            "setup(\n"
            f"  name={self.DIST_NAME!r},\n"
            f"  version={self.version!r},\n"
            "  packages=find_packages(),\n"
            "  include_package_data=True,\n"
            f"  package_data={self.PACKAGE_DATA!r},\n"
            "  install_requires=[\n"
            f"{install_requires}\n"
            "  ],\n"
            "  python_requires='>=3.9',\n"
            ")\n"
        )
        (tmp_path / "setup.py").write_text(setup_contents, encoding="utf-8")

    def _log_built_artifacts(self):
        produced = list(self.out_dir.glob(f"{self.DIST_NAME}-{self.version}*.whl"))
        if not produced:
            raise FileNotFoundError(f"no wheel produced for {self.DIST_NAME}-{self.version}")
        for wheel in produced:
            print(f"[INFO] built: {wheel.name}")

    @staticmethod
    def _should_ignore(path: Path) -> bool:
        if path.name in IGNORE_PATTERNS:
            return True
        if path.suffix in IGNORE_PATTERNS:
            return True
        return False

    @staticmethod
    def _stamp_init(pkg: Path):
        init = pkg / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    @staticmethod
    def _normalize_version(version: str) -> str:
        cleaned = version.strip()
        if cleaned.startswith("v") and re.match(r"^v\d", cleaned):
            cleaned = cleaned[1:]
        if not cleaned:
            raise ValueError("wheel version cannot be empty")
        return cleaned


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", help="Repository root. Defaults to the parent directory of this script.")
    parser.add_argument("--out-dir", help="Wheel output directory. Defaults to the directory containing this script.")
    parser.add_argument("--version", help="Wheel version. Defaults to the fixed public snapshot identifier.")
    return parser.parse_args()


def main() -> int:
    try:
        return APIWheelBuilderCI.from_args(parse_args()).build()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
