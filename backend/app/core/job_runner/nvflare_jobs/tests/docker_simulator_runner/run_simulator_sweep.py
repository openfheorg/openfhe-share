#!/usr/bin/env python3
"""Run the NVFlare biomarker sweep against a selected datasource.

The test modules retain their default ``2_1`` value for direct local execution,
but their fixture uses ``setdefault``. This runner injects the selected physical
datasource key before pytest starts, so the FHIR engine, model lookup, and
datasource-group config all use the same real identity.

    --datasource 2_1
        -> model files: project_2/datasource_group_1
        -> schema:      global_schema/project_2/datasource_group_1
        -> site inputs: DUALITY_CLIENT_SITE{1,2,3}_DATASOURCE_2_1 from
                         standalone/default.env.local (or standalone/.env.local)
        -> container runtime: DUALITY_SIM_DATASOURCE_VERSION=2_1

The runner does not mount or copy the env file into Docker. It reads only the
three datasource assignments needed for the requested key, resolves their host
files, then passes the resulting container paths explicitly.

Two run modes (``--mode``, default ``lean``):
  * ``lean``  — records only pass/fail/skip + each test's detail (beta/p/max_delta);
                runs cases in parallel (pytest-xdist, RAM-capped), disables
                profiling, and writes no performance/taskflow artifacts. Smallest,
                fastest. The default because most runs only need correctness.
  * ``full``  — adds per-party profiling, the taskflow trace diagrams, and the
                performance report; runs serially so per-case timing is comparable.
                Use it for a definitive performance checkpoint.
See README.md § "Run modes" for details.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

RUNNER_DIR = Path(__file__).resolve().parent
JOBS_RELATIVE = Path("backend/app/core/job_runner/nvflare_jobs")
DATA_RELATIVE = Path("standalone/nvflare_stage/data")
MODELS_RELATIVE = Path("standalone/client_utils/model_files")
IMAGE_DEFAULT = "duality-nvflare-biomarker-sweep:2.7.2"

SUITE_TARGETS: Final = {
    "all": "tests/",
    # Individual analyses (one analysis per job): lcs = logistic calibration
    # (meta-analysis), km = survival Kaplan-Meier biomarker discovery.
    "lcs_open": "tests/test_simulator_sweep_lcs_open.py",
    "km_open": "tests/test_simulator_sweep_km_open.py",
    "lcs_enc": "tests/test_simulator_sweep_lcs_enc.py",
    "km_enc": "tests/test_simulator_sweep_km_enc.py",
    # Combined (KM AND LCS for one model in a single job, sharing one score
    # computation -- the reuse payoff).
    "combined_open": "tests/test_simulator_sweep_combined_open.py",
    "combined_enc": "tests/test_simulator_sweep_combined_enc.py",
    # Secure threshold-samples pre-pass: five deterministic end-to-end cases on the
    # open-KM chain (pass verdicts for both mask configs, forced extreme masks, and
    # the below-threshold stop). Not parametrized per (cancer, model) pair.
    "threshold": "tests/test_simulator_threshold_secure.py",
}

# Number of parametrized sweep test files each suite collects, used only for the
# informational "N requested test(s)" estimate. "all" (= the whole tests/ dir)
# collects the six sweep files (lcs/km/combined x open/enc); every single-file
# suite collects one. The threshold suite's five cases are fixed (not per-pair),
# so it stays out of the pairs-based estimate.
SUITE_TEST_FILE_COUNT: Final = {
    "all": 6,
    "lcs_open": 1,
    "km_open": 1,
    "lcs_enc": 1,
    "km_enc": 1,
    "combined_open": 1,
    "combined_enc": 1,
    "threshold": 0,
}

# The threshold suite is not pair-parametrized: five fixed cases, run without the
# supported-pairs -k filter (see the effective_keyword construction).
THRESHOLD_SUITE_CASES: Final = 5

# The test fixture's default is 2_1, but it intentionally uses setdefault.
# The runner supplies the selected physical key before pytest begins so no test
# source changes are needed for datasource-group-specific FHIR configuration.
SITE_ORDER: Final = ("site1", "site2", "site3")

# Recognition/ordering matrix for model-pair discovery (the legacy
# datasource_group_1 catalog; every current group's cancers are a subset).
# The tests parametrize themselves from the same model directory at collection
# time (conftest.sweep_cancers), so this list no longer drives which cases
# exist — it only orders discovered pairs and flags unknown cancer types as
# "unrecognized" in the discovery manifest.
SWEEP_CANCERS: Final = (
    "Bladder Cancer",
    "Breast Carcinoma",
    "Cancer of Unknown Primary",
    "Colorectal Cancer",
    "Endometrial Cancer",
    "Esophagogastric Carcinoma",
    "Gastrointestinal Neuroendocrine Tumor",
    "Gastrointestinal Stromal Tumor",
    "Glioma",
    "Melanoma",
    "Non-Hodgkin Lymphoma",
    "Non-Small Cell Lung Cancer",
    "Ovarian Cancer",
    "Pancreatic Cancer",
    "Prostate Cancer",
    "Renal Cell Carcinoma",
    "Skin Cancer, Non-Melanoma",
    "Soft Tissue Sarcoma",
    "Thyroid Cancer",
)
SWEEP_MODEL_KEYS: Final = ("cox_lasso", "logistic_reg")
MODEL_ARTIFACT_PATTERN: Final = re.compile(
    r"^(?P<model_key>cox_lasso|logistic_reg)_(?P<cancer_type>.+)_(?P<kind>weights|cutoff)\.csv$",
    re.IGNORECASE,
)
DATASOURCE_KEY_PATTERN: Final = re.compile(r"^(?P<project>\d+)_(?P<group>\d+)$")
DATASOURCE_ENV_PATTERN: Final = re.compile(
    r"^DUALITY_(?P<owner>SERVER|CLIENT_SITE(?P<site>\d+))_DATASOURCE_"
    r"(?P<project>\d+)_(?P<group>\d+)$"
)


class RunnerError(RuntimeError):
    """Host-side configuration error with an actionable message."""


@dataclass(frozen=True)
class DatasourceSpec:
    """Physical Project-2 datasource assets adapted to the fixed test interface."""

    key: str
    project_id: int
    datasource_group_id: int
    env_file: Path
    model_dir: Path
    global_schema: Path
    site_inputs: dict[str, Path]
    site_assignment_values: dict[str, str]
    server_assignment_value: str | None


@dataclass(frozen=True)
class SupportedPairInventory:
    """Complete fixed-matrix pairs found in a datasource's model package."""

    complete_pairs: tuple[tuple[str, str], ...]
    missing_artifacts: dict[str, dict[str, list[str]]]
    unrecognized_complete_pairs: tuple[tuple[str, str], ...]
    artifact_paths: dict[str, dict[str, list[str]]]

    @property
    def keyword_expression(self) -> str:
        return " or ".join(
            f"({_case_id(cancer)} and {model_key})"
            for cancer, model_key in self.complete_pairs
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "supported_pairs": [
                {"cancer_type": cancer, "model_key": model_key}
                for cancer, model_key in self.complete_pairs
            ],
            "supported_pair_count": len(self.complete_pairs),
            "expected_test_count_all_modes": len(self.complete_pairs) * SUITE_TEST_FILE_COUNT["all"],
            "missing_artifacts": self.missing_artifacts,
            "unrecognized_complete_pairs": [
                {"cancer_type": cancer, "model_key": model_key}
                for cancer, model_key in self.unrecognized_complete_pairs
            ],
            "artifact_paths": self.artifact_paths,
        }


@dataclass
class Summary:
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0

    @property
    def passed(self) -> int:
        return max(0, self.tests - self.failures - self.errors - self.skipped)


def _case_id(cancer_type: str) -> str:
    return cancer_type.replace(" ", "_").replace(",", "").replace("/", "_")


def heading(message: str) -> None:
    print(f"\n{'=' * 78}\n{message}\n{'=' * 78}", flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_share_root(explicit: str | None) -> Path:
    def is_share_root(candidate: Path) -> bool:
        return (
            (candidate / JOBS_RELATIVE / "tests").is_dir()
            and (candidate / DATA_RELATIVE).is_dir()
        )

    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if is_share_root(candidate):
            return candidate
        raise RunnerError(
            "--share-root must contain both:\n"
            f"  {JOBS_RELATIVE / 'tests'}\n"
            f"  {DATA_RELATIVE}\n"
            f"Received: {candidate}"
        )

    for candidate in (RUNNER_DIR, *RUNNER_DIR.parents):
        if is_share_root(candidate):
            return candidate

    raise RunnerError(
        "Could not locate the share root. Put this folder at\n"
        "  backend/app/core/job_runner/nvflare_jobs/tests/docker_simulator_runner/\n"
        "inside the share checkout, or pass --share-root <path>."
    )


def require_docker() -> None:
    if shutil.which("docker") is None:
        raise RunnerError("Docker was not found on PATH. Start Docker Desktop and reopen the terminal.")
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RunnerError(
            "Docker is installed but the Linux engine is unavailable. "
            "Start Docker Desktop and ensure Linux containers are enabled."
            + (f"\nDocker detail: {detail}" if detail else "")
        ) from exc
    print(f"Docker engine: {completed.stdout.strip()}", flush=True)


def docker_mount(source: Path, target: str, *, readonly: bool) -> list[str]:
    spec = f"type=bind,source={source.resolve()},target={target}"
    if readonly:
        spec += ",readonly"
    return ["--mount", spec]


def run_checked(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def build_image(image: str, rebuild: bool) -> None:
    command = [
        "docker",
        "build",
        "--tag",
        image,
        "--build-arg",
        "NVFLARE_VERSION=2.7.2",
        "--file",
        str(RUNNER_DIR / "Dockerfile"),
    ]
    if rebuild:
        command.append("--no-cache")
    command.append(str(RUNNER_DIR))
    heading("Building Linux NVFlare 2.7.2 simulator image")
    run_checked(command)


def parse_datasource_key(raw: str) -> tuple[int, int]:
    match = DATASOURCE_KEY_PATTERN.fullmatch(raw.strip())
    if not match:
        raise RunnerError(
            "--datasource must be exactly <project_id>_<datasource_group_id>, for example 2_1."
        )
    project_id = int(match.group("project"))
    datasource_group_id = int(match.group("group"))
    if project_id != 2:
        raise RunnerError(
            f"The current biomarker sweep is parameterized for Project 2 model packages; "
            f"--datasource {raw!r} resolves to Project {project_id}."
        )
    if datasource_group_id != 1:
        raise RunnerError(
            f"The public OpenFHE snapshot supports only datasource 2_1; got {raw!r}."
        )
    return project_id, datasource_group_id


def find_env_file(explicit: str | None, share_root: Path, *, required: bool) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = share_root / path
        path = path.resolve()
        if not path.is_file():
            raise RunnerError(f"--env-file is not a file: {path}")
        return path

    candidates = (
        share_root / "standalone" / "default.env.local",
        share_root / "standalone" / ".env.local",
        share_root / "default.env.local",
        share_root / ".env.local",
    )
    for path in candidates:
        if path.is_file():
            return path.resolve()

    if required:
        expected = "\n  ".join(str(path) for path in candidates)
        raise RunnerError(
            "Could not find a datasource environment file. Expected one of:\n"
            f"  {expected}\n\n"
            "Pass --env-file <path-to-default.env.local> to choose it explicitly."
        )
    return None


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _expand_variables(value: str, variables: dict[str, str]) -> str:
    pattern = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
    for _ in range(10):
        expanded = pattern.sub(
            lambda match: variables.get(match.group("braced") or match.group("plain") or "", match.group(0)),
            value,
        )
        if expanded == value:
            return expanded
        value = expanded
    return value


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments without evaluating shell code."""
    variables: dict[str, str] = {}
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise RunnerError(f"Unsupported dotenv line {line_no} in {path}: {raw_line!r}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise RunnerError(f"Invalid dotenv key on line {line_no} in {path}: {key!r}")
        value = _strip_inline_comment(raw_value.strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        variables[key] = _expand_variables(value, {**os.environ, **variables})
    return variables


def _candidate_paths_for_value(
    raw: str,
    *,
    env_file: Path,
    share_root: Path,
    data_roots: tuple[Path, ...],
) -> list[Path]:
    raw = raw.strip()
    if not raw:
        return []
    # Let Path retain native Windows semantics when this runner executes on Windows.
    source_path = Path(raw).expanduser()
    candidates: list[Path] = []
    if source_path.is_absolute():
        candidates.append(source_path)
    else:
        candidates.extend((env_file.parent / source_path, share_root / source_path))
        candidates.extend(root / source_path for root in data_roots)

    # Deployment env files often use a path inside a standalone container (for
    # example /data/foo.json). Resolve that by exact basename under explicitly
    # approved host data roots; do not search the full checkout.
    slash_normalized = raw.replace("\\", "/")
    basename = Path(slash_normalized).name
    if basename:
        candidates.extend(root / basename for root in data_roots)
        parts = [part for part in slash_normalized.split("/") if part]
        if "data" in parts:
            tail = Path(*parts[parts.index("data") + 1 :])
            if tail.parts:
                candidates.extend(root / tail for root in data_roots)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def refresh_json_from_zip(json_path: Path, *, assignment_name: str) -> Path:
    """Re-extract a resolved datasource JSON when its sibling ZIP is newer.

    Only the ZIPs are tracked, so a data update arrives as a new archive beside an
    already-extracted JSON. Same rule as client_utils.create_client, applied here so
    a sweep cannot silently validate against data the repository no longer carries.
    """
    if json_path.suffix.lower() != ".json":
        return json_path

    zip_path = json_path.with_suffix(".zip")
    if not zip_path.is_file():
        return json_path
    if json_path.is_file() and json_path.stat().st_mtime >= zip_path.stat().st_mtime:
        return json_path

    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        member = next((name for name in members if Path(name).name == json_path.name), None)
        if member is None:
            json_members = [name for name in members if Path(name).suffix.lower() == ".json"]
            if len(json_members) != 1:
                preview = ", ".join(json_members[:12]) or "<none>"
                raise RunnerError(
                    f"{assignment_name}: cannot refresh {json_path.name} from {zip_path.name}. "
                    f"Archive JSON members: {preview}"
                )
            member = json_members[0]

        staged = json_path.with_name(f"{json_path.name}.from-zip.{os.getpid()}")
        try:
            with archive.open(member) as source, staged.open("wb") as target:
                shutil.copyfileobj(source, target)
            staged.replace(json_path)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

    # Stamp the extraction time, not the archive member's date, or the JSON stays
    # older than the ZIP and every later run re-extracts the same bytes.
    os.utime(json_path, None)
    print(f"Refreshed {json_path.name} from {zip_path.name} ({zip_path.stat().st_size} B archive was newer).")
    return json_path


def resolve_assigned_input(
    raw: str,
    *,
    assignment_name: str,
    env_file: Path,
    share_root: Path,
    data_roots: tuple[Path, ...],
) -> Path:
    candidates = _candidate_paths_for_value(
        raw,
        env_file=env_file,
        share_root=share_root,
        data_roots=data_roots,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    basename = Path(raw.replace("\\", "/")).name
    matches: list[Path] = []
    if basename:
        for root in data_roots:
            if root.is_dir():
                matches.extend(path.resolve() for path in root.rglob(basename) if path.is_file())
    matches = sorted(set(matches))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        formatted = "\n  ".join(str(path) for path in matches[:12])
        raise RunnerError(
            f"{assignment_name}={raw!r} could not be mapped uniquely from {env_file}. "
            f"Multiple host files named {basename!r} were found:\n  {formatted}\n\n"
            "Use --data-root to restrict the search roots."
        )

    attempted = "\n  ".join(str(path) for path in candidates)
    raise RunnerError(
        f"{assignment_name}={raw!r} from {env_file} did not resolve to a host file. Tried:\n"
        f"  {attempted}\n\n"
        "The runner accepts JSON and ZIP FHIR inputs. If this environment value is a "
        "container-only path, pass --data-root <host directory containing that file>."
    )


def resolve_data_roots(args: argparse.Namespace, share_root: Path, env_file: Path) -> tuple[Path, ...]:
    roots: list[Path] = [share_root / DATA_RELATIVE, env_file.parent]
    for raw in args.data_root:
        root = Path(raw).expanduser()
        if not root.is_absolute():
            root = share_root / root
        root = root.resolve()
        if not root.is_dir():
            raise RunnerError(f"--data-root is not a directory: {root}")
        roots.append(root)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            deduped.append(resolved)
            seen.add(resolved)
    return tuple(deduped)


def resolve_datasource_spec(
    args: argparse.Namespace,
    share_root: Path,
    *,
    require_site_inputs: bool,
) -> DatasourceSpec:
    project_id, datasource_group_id = parse_datasource_key(args.datasource)
    key = f"{project_id}_{datasource_group_id}"
    model_dir = share_root / MODELS_RELATIVE / f"project_{project_id}" / f"datasource_group_{datasource_group_id}"
    global_schema = (
        share_root
        / JOBS_RELATIVE
        / "global_schema"
        / f"project_{project_id}"
        / f"datasource_group_{datasource_group_id}"
        / "global_schema.json"
    )

    if not model_dir.is_dir():
        raise RunnerError(
            f"Model directory is missing for --datasource {key}:\n  {model_dir}"
        )
    if not any(path.is_file() for path in model_dir.rglob("*")):
        raise RunnerError(f"Model directory is empty for --datasource {key}:\n  {model_dir}")
    if not global_schema.is_file():
        raise RunnerError(
            f"Global schema is missing for --datasource {key}:\n  {global_schema}"
        )
    try:
        schema_payload = json.loads(global_schema.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunnerError(f"Global schema is not valid JSON: {global_schema}\n{exc}") from exc
    if not isinstance(schema_payload, dict):
        raise RunnerError(f"Global schema must contain a JSON object: {global_schema}")

    env_file = find_env_file(args.env_file, share_root, required=require_site_inputs)
    if env_file is None:
        # Only valid for --list-supported-pairs; there are no site inputs to resolve.
        return DatasourceSpec(
            key=key,
            project_id=project_id,
            datasource_group_id=datasource_group_id,
            env_file=Path("<not-required>"),
            model_dir=model_dir.resolve(),
            global_schema=global_schema.resolve(),
            site_inputs={},
            site_assignment_values={},
            server_assignment_value=None,
        )

    dotenv = parse_dotenv(env_file)
    assignments: dict[str, str] = {}
    server_value: str | None = None
    for env_name, value in dotenv.items():
        match = DATASOURCE_ENV_PATTERN.fullmatch(env_name)
        if not match:
            continue
        if int(match.group("project")) != project_id or int(match.group("group")) != datasource_group_id:
            continue
        site = match.group("site")
        if site is None:
            server_value = value
        else:
            assignments[f"site{site}"] = value

    missing_sites = [site for site in SITE_ORDER if not assignments.get(site)]
    if missing_sites:
        expected = "\n  ".join(
            f"DUALITY_CLIENT_{site.upper()}_DATASOURCE_{key}" for site in missing_sites
        )
        raise RunnerError(
            f"{env_file} does not define every required simulated-client datasource for {key}. "
            f"Missing:\n  {expected}\n\n"
            "The unchanged sweep always starts site1, site2, and site3."
        )

    data_roots = resolve_data_roots(args, share_root, env_file)
    site_inputs: dict[str, Path] = {}
    for site in SITE_ORDER:
        env_name = f"DUALITY_CLIENT_{site.upper()}_DATASOURCE_{key}"
        site_inputs[site] = refresh_json_from_zip(
            resolve_assigned_input(
                assignments[site],
                assignment_name=env_name,
                env_file=env_file,
                share_root=share_root,
                data_roots=data_roots,
            ),
            assignment_name=env_name,
        )

    return DatasourceSpec(
        key=key,
        project_id=project_id,
        datasource_group_id=datasource_group_id,
        env_file=env_file.resolve(),
        model_dir=model_dir.resolve(),
        global_schema=global_schema.resolve(),
        site_inputs=site_inputs,
        site_assignment_values={site: assignments[site] for site in SITE_ORDER},
        server_assignment_value=server_value,
    )


def discover_supported_pairs(model_dir: Path) -> SupportedPairInventory:
    artifacts: dict[tuple[str, str], dict[str, list[str]]] = {}
    for path in sorted(candidate for candidate in model_dir.rglob("*") if candidate.is_file()):
        match = MODEL_ARTIFACT_PATTERN.match(path.name)
        if not match:
            continue
        model_key = match.group("model_key").lower()
        cancer_type = match.group("cancer_type").strip()
        kind = match.group("kind").lower()
        artifacts.setdefault((cancer_type, model_key), {}).setdefault(kind, []).append(
            str(path.relative_to(model_dir))
        )

    fixed_matrix = {(cancer, model_key) for cancer in SWEEP_CANCERS for model_key in SWEEP_MODEL_KEYS}
    complete: list[tuple[str, str]] = []
    missing: dict[str, dict[str, list[str]]] = {}
    unrecognized: list[tuple[str, str]] = []
    manifest_artifacts: dict[str, dict[str, list[str]]] = {}

    for (cancer_type, model_key), kinds in sorted(artifacts.items()):
        display_key = f"{cancer_type} / {model_key}"
        manifest_artifacts[display_key] = {kind: sorted(paths) for kind, paths in sorted(kinds.items())}
        required = {"weights", "cutoff"}
        available = set(kinds)
        if required <= available:
            if (cancer_type, model_key) in fixed_matrix:
                complete.append((cancer_type, model_key))
            else:
                unrecognized.append((cancer_type, model_key))
        elif (cancer_type, model_key) in fixed_matrix:
            missing[display_key] = {
                "missing": sorted(required - available),
                "available": sorted(available),
            }

    ordered = sorted(
        complete,
        key=lambda pair: (SWEEP_CANCERS.index(pair[0]), SWEEP_MODEL_KEYS.index(pair[1])),
    )
    return SupportedPairInventory(
        complete_pairs=tuple(ordered),
        missing_artifacts=missing,
        unrecognized_complete_pairs=tuple(unrecognized),
        artifact_paths=manifest_artifacts,
    )


def combine_keywords(auto_keyword: str | None, user_keyword: str | None) -> str | None:
    if auto_keyword and user_keyword:
        return f"({auto_keyword}) and ({user_keyword})"
    return auto_keyword or user_keyword


def datasource_manifest(spec: DatasourceSpec, inventory: SupportedPairInventory) -> dict[str, object]:
    schema_payload = json.loads(spec.global_schema.read_text(encoding="utf-8"))
    return {
        "physical_datasource": {
            "key": spec.key,
            "project_id": spec.project_id,
            "datasource_group_id": spec.datasource_group_id,
            "env_file": str(spec.env_file),
            "site_assignments_from_env": spec.site_assignment_values,
            "server_assignment_from_env": spec.server_assignment_value,
            "resolved_site_inputs": {site: str(spec.site_inputs[site]) for site in SITE_ORDER},
        },
        "simulator_runtime_identity": {
            "project_id": spec.project_id,
            "datasource_group_id": spec.datasource_group_id,
            "datasource_key": spec.key,
            "sim_datasource_version": spec.key,
            "model_mount_target": (
                f"/source-models/datasource_group_{spec.datasource_group_id}"
            ),
            "note": (
                "The test fixture default is overridden by the selected "
                "DUALITY_SIM_DATASOURCE_VERSION before pytest starts."
            ),
        },
        "selected_assets": {
            "model_dir": str(spec.model_dir),
            "model_file_count": len([path for path in spec.model_dir.rglob("*") if path.is_file()]),
            "global_schema": str(spec.global_schema),
            "global_schema_sha256": sha256(spec.global_schema),
            "biomarker_covariate_count": len(
                (schema_payload.get("metadata", {}) or {}).get("biomarker_covariates") or []
            ),
        },
        "model_pair_inventory": inventory.to_manifest(),
    }


def create_results_dir(parent: Path | None) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination_parent = parent.resolve() if parent else RUNNER_DIR / "test-results"
    destination = destination_parent / f"simulator-sweep-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def run_container(
    *,
    image: str,
    jobs_dir: Path,
    spec: DatasourceSpec,
    results_dir: Path,
    suite: str,
    keyword: str | None,
    selected_pairs: SupportedPairInventory,
    pytest_args: list[str],
    shm_size: str | None,
    mode: str,
    jobs: int,
) -> int:
    # Size /dev/shm to the parallel case count unless the user set --shm-size
    # explicitly. Each concurrent lean case stages its own crypto context +
    # rotation keys into /dev/shm, so a flat 2g starves cases at higher -n.
    # --shm-size only sets the tmpfs ceiling (nothing is preallocated), so an
    # over-estimate from host cores is harmless.
    if shm_size is None:
        if mode == "lean":
            # jobs <= 0 means the container auto-picks min(cores, RAM); estimate the
            # upper bound from host cores when the exact -n is not known here.
            effective_jobs = jobs if jobs > 0 else (os.cpu_count() or 1)
        else:
            effective_jobs = 1  # full mode runs serially
        shm_size = f"{max(2, 2 * effective_jobs)}g"
    command = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--shm-size",
        shm_size,
        # Mount the entrypoint and override the image entrypoint so pure runner
        # changes continue to work with --no-build.
        "--entrypoint",
        "/usr/local/bin/python3",
    ]
    command += docker_mount(RUNNER_DIR / "container_entrypoint.py", "/work/runner_entrypoint.py", readonly=True)
    command += docker_mount(RUNNER_DIR / "pytest_sweep_reporter.py", "/work/pytest_sweep_reporter.py", readonly=True)
    command += docker_mount(jobs_dir, "/source/nvflare_jobs", readonly=True)
    command += docker_mount(spec.model_dir, f"/source-models/datasource_group_{spec.datasource_group_id}", readonly=True)
    command += docker_mount(spec.global_schema, "/work/profile-global_schema.json", readonly=True)
    command += docker_mount(results_dir, "/results", readonly=False)

    runtime_inputs: dict[str, str] = {}
    for site in SITE_ORDER:
        host_path = spec.site_inputs[site]
        target = f"/work/source-input-{site}-{host_path.name}"
        command += docker_mount(host_path, target, readonly=True)
        runtime_inputs[site] = target

    environment = {
        "DUALITY_TEST_TARGET": SUITE_TARGETS[suite],
        "DUALITY_TEST_PYTEST_ARGS": json.dumps(pytest_args),
        "DUALITY_SIM_DATASOURCE_VERSION": spec.key,
        "DUALITY_SIM_BIOMARKER_MODELS_ROOT": "/source-models",
        "DUALITY_RUNNER_DATASOURCE_KEY": spec.key,
        "DUALITY_RUNNER_SIM_DATASOURCE_KEY": spec.key,
        "DUALITY_RUNNER_GLOBAL_SCHEMA": "/work/profile-global_schema.json",
        "DUALITY_RUNNER_SITE1_INPUT": runtime_inputs["site1"],
        "DUALITY_RUNNER_SITE2_INPUT": runtime_inputs["site2"],
        "DUALITY_RUNNER_SITE3_INPUT": runtime_inputs["site3"],
        "DUALITY_NVFLARE_LIB_UPDATE_DISABLED": "1",
        "DUALITY_SWEEP_MODE": mode,
        "DUALITY_SWEEP_JOBS": str(jobs),
    }
    if keyword:
        environment["DUALITY_TEST_KEYWORD"] = keyword
    he_workers = os.environ.get("OPENFHE_BIOMARKER_MAX_WORKERS", "").strip()
    if he_workers:
        environment["OPENFHE_BIOMARKER_MAX_WORKERS"] = he_workers
    # Opt-in INSECURE CKKS ring dimension for cheaper keys/ciphertexts in test runs. Forwarded
    # only when set on the host; unset => the parties build a full 128-bit-security context.
    # One value covers the server and every client (they share the container environment).
    ring_dim = os.environ.get("DUALITY_SIM_CKKS_RING_DIM", "").strip()
    if ring_dim:
        environment["DUALITY_SIM_CKKS_RING_DIM"] = ring_dim
    # Let the (root) container hand its /results outputs back to us on exit, so
    # regenerating or deleting sweep results never needs sudo.
    if hasattr(os, "getuid"):
        environment["DUALITY_HOST_UID"] = str(os.getuid())
        environment["DUALITY_HOST_GID"] = str(os.getgid())
    for key, value in environment.items():
        command += ["--env", f"{key}={value}"]

    command.extend((image, "/work/runner_entrypoint.py"))

    heading(f"Running {suite} simulator sweep for physical datasource {spec.key}")
    print(f"Runner entrypoint:   {RUNNER_DIR / 'container_entrypoint.py'} -> /work/runner_entrypoint.py (read-only)")
    print(f"Pytest reporter:     {RUNNER_DIR / 'pytest_sweep_reporter.py'} -> /work/pytest_sweep_reporter.py (read-only)")
    print(f"NVFlare source mount: {jobs_dir} -> /source/nvflare_jobs (read-only)")
    for site in SITE_ORDER:
        print(
            f"{site} FHIR input:       {spec.site_inputs[site]} -> {runtime_inputs[site]} (read-only)"
        )
    print(f"Model files mount:    {spec.model_dir} -> /source-models/datasource_group_{spec.datasource_group_id} (read-only)")
    print(f"Global schema mount:  {spec.global_schema} -> /work/profile-global_schema.json (read-only)")
    print(f"Results directory:    {results_dir}")
    print(
        "Simulator runtime identity: "
        f"Project {spec.project_id} / datasource group {spec.datasource_group_id} "
        f"({spec.key})."
    )
    if mode == "lean":
        n_note = "auto" if jobs <= 0 else str(jobs)
        he_env = os.environ.get("OPENFHE_BIOMARKER_MAX_WORKERS", "").strip()
        he_note = he_env if he_env else "1"
        mode_note = f"parallel -n {n_note}=min(cores,RAM/worker), HE workers={he_note}, no profiling/perf artifacts"
    else:
        mode_note = "serial, full profiling + perf report"
    print(f"Sweep mode:           {mode} ({mode_note})")
    if suite == "threshold":
        print(f"Model-pair selection: not applicable ({THRESHOLD_SUITE_CASES} fixed threshold test(s))")
    else:
        count = len(selected_pairs.complete_pairs) * SUITE_TEST_FILE_COUNT[suite]
        print(f"Model-pair selection: {len(selected_pairs.complete_pairs)} discovered supported pair(s) = {count} requested test(s)")
    for cancer_type, model_key in selected_pairs.complete_pairs:
        print(f"  - {cancer_type} / {model_key}")
    print("The image/container never receives default.env.local or the full share checkout.", flush=True)
    print("", flush=True)
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command).returncode


def junit_summary(path: Path, mode: str) -> tuple[Summary, list[str]]:
    # full-console-output.txt only exists in full mode; in lean the container
    # error surfaces in pytest-output.txt (and the container stdout / docker logs).
    console_hint = "full-console-output.txt" if mode == "full" else "pytest-output.txt"
    if not path.is_file():
        return Summary(errors=1), [f"No junit.xml was created. Read {console_hint} for the container error."]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return Summary(errors=1), [f"Could not parse junit.xml: {exc}"]

    result = Summary()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    for suite in suites:
        result.tests += int(suite.attrib.get("tests", "0"))
        result.failures += int(suite.attrib.get("failures", "0"))
        result.errors += int(suite.attrib.get("errors", "0"))
        result.skipped += int(suite.attrib.get("skipped", "0"))

    problems: list[str] = []
    for test in root.iter("testcase"):
        identifier = "::".join(
            part for part in (test.attrib.get("classname", ""), test.attrib.get("name", "")) if part
        )
        for tag in ("failure", "error"):
            element = test.find(tag)
            if element is None:
                continue
            message = (element.attrib.get("message") or "").strip()
            detail = (element.text or "").strip()
            detail_first = next((line.strip() for line in detail.splitlines() if line.strip()), "")
            if detail_first and detail_first not in message:
                message = f"{message} | {detail_first}".strip(" |")
            problems.append(f"{identifier or '<collection>'}: {message or tag}")
    return result, problems


def print_summary(results_dir: Path, exit_code: int, mode: str) -> None:
    summary, problems = junit_summary(results_dir / "junit.xml", mode)
    heading("Simulator sweep result summary")
    print(f"Container exit code: {exit_code}")
    print(
        f"Pytest: {summary.tests} collected | {summary.passed} passed | "
        f"{summary.skipped} skipped | {summary.failures} failed | {summary.errors} errors"
    )
    # Only list artifacts that were actually written; lean mode omits the
    # profiling/performance/taskflow outputs and prunes the workspaces.
    artifacts = [
        ("Pytest report", "pytest-output.txt"),
        ("Status events", "pytest-status-events.jsonl"),
        ("JUnit report", "junit.xml"),
        ("Datasource manifest", "runner-datasource.json"),
        ("Model pair inventory", "supported-model-pairs.json"),
        ("Performance report", "performance-output.txt"),
        ("Performance JSON", "performance-summary.json"),
        ("Taskflow traces", "taskflow"),
        ("Full console log", "full-console-output.txt"),
        ("Simulator workspaces", "simulator-workspaces"),
    ]
    for label, name in artifacts:
        path = results_dir / name
        if path.exists():
            print(f"{label + ':':<22}{path}")
    if problems:
        print("\nFailures/errors:")
        for problem in problems[:10]:
            print(textwrap.indent(problem, "  - "))
        if len(problems) > 10:
            console_hint = "full-console-output.txt" if mode == "full" else "pytest-output.txt"
            print(f"  ... plus {len(problems) - 10} more. See junit.xml / {console_hint}.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Run Project-2 NVFlare sweep tests against the selected "
            "physical Project-2 datasource group inside Linux Docker."
        )
    )
    result.add_argument(
        "--datasource",
        required=True,
        help="Physical datasource key: <project_id>_<datasource_group_id>, e.g. 2_1.",
    )
    result.add_argument("--suite", choices=sorted(SUITE_TARGETS), default="all")
    result.add_argument(
        "--mode",
        choices=("lean", "full"),
        default="lean",
        help=(
            "'lean' (default): record only pass/fail/skip + test detail (e.g. p-values), run cases "
            "in parallel, prune workspaces, and skip ALL profiling / taskflow / performance artifacts. "
            "'full': profile every party and generate the trace diagrams + performance report (the "
            "definitive perf checkpoint behavior)."
        ),
    )
    result.add_argument(
        "--jobs",
        type=int,
        default=0,
        help=(
            "lean mode only: parallel pytest-xdist workers (-n). 0 (default) = auto = "
            "min(cores, RAM-based cap). A positive value is still capped by cores and RAM at "
            "runtime so heavy cases can't OOM. Ignored in full mode (always serial)."
        ),
    )
    result.add_argument(
        "--list-supported-pairs",
        action="store_true",
        help="Print discovered supported model pairs and exit without resolving FHIR inputs or Docker.",
    )
    result.add_argument("--keyword", help="Additional pytest -k expression, e.g. 'Glioma and cox_lasso'.")
    result.add_argument("--share-root", help="Path to the share checkout. Normally discovered automatically.")
    result.add_argument(
        "--env-file",
        help=(
            "Datasource assignment file. Defaults to standalone/default.env.local, then "
            "standalone/.env.local, then equivalents at share root."
        ),
    )
    result.add_argument(
        "--data-root",
        action="append",
        default=[],
        help="Additional host directory to search for container-path datasource file names; repeatable.",
    )
    result.add_argument("--image", default=IMAGE_DEFAULT)
    result.add_argument("--results-dir", help="Parent directory for timestamped result folders.")
    result.add_argument("--rebuild", action="store_true", help="Build the Docker image with --no-cache.")
    result.add_argument("--no-build", action="store_true", help="Reuse the existing Docker image without building.")
    result.add_argument(
        "--shm-size",
        default=None,
        help=(
            "Docker shared memory (/dev/shm) size. Default: auto — max(2, 2*parallel jobs) GiB "
            "in lean, 2g in full. Pass an explicit value (e.g. 8g) to override the auto-scaling."
        ),
    )
    result.add_argument(
        "--pair-selection",
        choices=("supported", "all"),
        default="supported",
        help=(
            "'supported' (default) runs only discovered pairs with both weights/cutoff artifacts. "
            "'all' runs the full hardcoded cancer/model test matrix deliberately."
        ),
    )
    result.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Extra pytest argument; repeatable. Example: --pytest-arg=--maxfail=1",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.no_build and args.rebuild:
        raise RunnerError("--no-build and --rebuild cannot be used together.")

    share_root = locate_share_root(args.share_root)
    jobs_dir = share_root / JOBS_RELATIVE
    spec = resolve_datasource_spec(
        args,
        share_root,
        require_site_inputs=not args.list_supported_pairs,
    )
    inventory = discover_supported_pairs(spec.model_dir)

    if args.list_supported_pairs:
        heading(f"Supported fixed-matrix model pairs for physical datasource {spec.key}")
        print(f"Model directory: {spec.model_dir}")
        print(f"Global schema:   {spec.global_schema}")
        print(f"Supported pairs: {len(inventory.complete_pairs)}")
        for cancer_type, model_key in inventory.complete_pairs:
            print(f"  - {cancer_type} / {model_key}")
        if inventory.missing_artifacts:
            print("\nIncomplete fixed-matrix artifacts:")
            for pair, detail in inventory.missing_artifacts.items():
                print(f"  - {pair}: missing {', '.join(detail['missing'])}")
        if inventory.unrecognized_complete_pairs:
            print("\nComplete model pairs not represented by the unchanged sweep:")
            for cancer_type, model_key in inventory.unrecognized_complete_pairs:
                print(f"  - {cancer_type} / {model_key}")
        return 0

    if args.pair_selection == "supported" and not inventory.complete_pairs:
        raise RunnerError(
            "No supported fixed-matrix cancer/model pairs were discovered. Expected matching "
            "{cox_lasso|logistic_reg}_{cancer_type}_{weights|cutoff}.csv artifacts under:\n"
            f"  {spec.model_dir}\n\n"
            "Use --list-supported-pairs to inspect the model package, or pass --pair-selection all "
            "only when you deliberately want unsupported cases to execute."
        )

    selected_inventory = inventory
    # The supported-pairs -k expression only matches the pair-parametrized sweep case
    # ids; the threshold suite's five fixed cases (T10, mask_at_positive_clip, ...)
    # would all be deselected by it, so that suite runs unfiltered by pairs.
    apply_pair_keyword = args.pair_selection == "supported" and args.suite != "threshold"
    effective_keyword = combine_keywords(
        inventory.keyword_expression if apply_pair_keyword else None,
        args.keyword,
    )

    heading(f"Validating simulator sweep for datasource {spec.key}")
    print(f"Share root: {share_root}")
    print(f"Datasource environment file: {spec.env_file}")
    print(f"Model package: {spec.model_dir}")
    print(f"Global schema: {spec.global_schema}")
    for site in SITE_ORDER:
        print(
            f"  {site}: {spec.site_assignment_values[site]} -> {spec.site_inputs[site]}"
        )
    if spec.server_assignment_value:
        print(
            "  server assignment (not used by these non-server-owner sweep configs): "
            f"{spec.server_assignment_value}"
        )
    requested = (
        THRESHOLD_SUITE_CASES
        if args.suite == "threshold"
        else len(inventory.complete_pairs) * SUITE_TEST_FILE_COUNT[args.suite]
    )
    print(f"Discovered model pairs: {len(inventory.complete_pairs)} ({requested} requested test(s))")

    require_docker()
    if not args.no_build:
        build_image(args.image, args.rebuild)

    results_parent = Path(args.results_dir).expanduser() if args.results_dir else None
    if results_parent and not results_parent.is_absolute():
        results_parent = (share_root / results_parent).resolve()
    results_dir = create_results_dir(results_parent)
    manifest = datasource_manifest(spec, inventory)
    (results_dir / "runner-datasource.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (results_dir / "supported-model-pairs.json").write_text(
        json.dumps(inventory.to_manifest(), indent=2), encoding="utf-8"
    )

    exit_code = run_container(
        image=args.image,
        jobs_dir=jobs_dir,
        spec=spec,
        results_dir=results_dir,
        suite=args.suite,
        keyword=effective_keyword,
        selected_pairs=selected_inventory,
        pytest_args=args.pytest_arg,
        shm_size=args.shm_size,
        mode=args.mode,
        jobs=args.jobs,
    )
    print_summary(results_dir, exit_code, args.mode)
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
