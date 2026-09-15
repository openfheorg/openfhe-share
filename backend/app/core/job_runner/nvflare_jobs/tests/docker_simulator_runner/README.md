# Generic datasource-key NVFlare simulator runner

This runner executes the existing biomarker sweep tests without modifying their
source or `NVFlareJobStager`. The selected datasource key is injected into the
container before pytest starts, overriding the tests' `2_1` default through the
existing `setdefault` behavior.

Use a real physical datasource key instead of a named profile:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1
```

## Run modes: `lean` (default) and `full`

`--mode` selects *how much* the sweep records. It is independent of `--suite`
(which selects *which* tests run).

```text
lean (default)  Fastest, smallest. Records only pass/fail/skip + each test's own
                detail (beta/p/max_delta). Strips both the profiler component and
                the trace-correlation filter, so it writes no profiling, trace
                diagrams, or performance report and adds no per-message trace
                overhead. Cases run in parallel (pytest-xdist) with the HE
                aggregation pinned to 1 worker/case, and each PASSED case's
                simulator workspace is deleted as soon as it finishes (failed
                cases are kept for debugging).
full            Everything lean records, plus per-party profiling, the taskflow
                trace diagrams, and the performance report. Runs serially so the
                per-case timing stays comparable. Use it for a definitive
                performance checkpoint.
```

Lean pins the HE aggregation to 1 worker per case (`OPENFHE_BIOMARKER_MAX_WORKERS=1`)
and auto-sizes `-n`: `--jobs` (default `0` = auto) resolves at runtime to
`min(cores, floor(total_RAM / 8 GB per case per HE worker))` (3 on a 16-core / 27 GB
host), where the RAM budget is read from a cgroup memory limit when one is set and
`cores` is the process's schedulable CPU set. A positive `--jobs` is capped the same way
so heavy cases can't OOM; a forwarded host `OPENFHE_BIOMARKER_MAX_WORKERS` still wins and
re-budgets `-n` (8 GB × workers per case), and `--shm-size` auto-scales with the job
count unless set explicitly. Full mode is always serial with auto HE workers. Lean's `-n`
needs `pytest-xdist` in the image — rebuild if reusing an old one.

### Lean reduces CKKS security

Lean also pins CKKS **ring dimension 4096** (`conftest.LEAN_CKKS_RING_DIM`) instead of the
32768 that `HEStd_128_classic` selects, which is what makes its keys and ciphertexts cheap.
Full mode and a bare-host `pytest` stay at full security. Every run prints the effective
value, so a run's security level is never inferred from its timings:

```text
CKKS ring dimension: 4096 (DUALITY_SWEEP_MODE=lean)
```

`DUALITY_SIM_CKKS_RING_DIM` overrides it in either mode. The `-n` budget above assumes the
reduced ring, so **a full-ring override must not be combined with lean parallelism** —
full-ring cases are several times larger and will exhaust host memory. Pass `--jobs 1`:

```bash
DUALITY_SIM_CKKS_RING_DIM=32768 python tests/docker_simulator_runner/run_simulator_sweep.py \
  --no-build --datasource 2_1 --suite km_enc --jobs 1
```

The reduced ring is worth 15% of sweep wall time, but only for some suites: `km_open` 0.57x
and `km_enc` 0.85x (their 97-point time grid is one ciphertext at any batch size), while
`lcs_enc` is 1.08x *slower* — its depth-4 dot product is already cheap, so the per-ciphertext
saving cannot offset 8x more ciphertexts to encrypt and ship.

```bash
# lean (default): parallel, correctness-only, kilobyte-sized output
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1

# full: profiling + diagrams + performance report (the perf-checkpoint behavior)
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --mode full
```

## What `--datasource 2_1` does

The runner derives the physical assets from the requested key:

```text
models:
standalone/client_utils/model_files/project_2/datasource_group_1/

schema:
backend/app/core/job_runner/nvflare_jobs/global_schema/project_2/datasource_group_1/global_schema.json

FHIR site assignments:
DUALITY_CLIENT_SITE1_DATASOURCE_2_1
DUALITY_CLIENT_SITE2_DATASOURCE_2_1
DUALITY_CLIENT_SITE3_DATASOURCE_2_1
```

The site assignments are read from the first available file in this order:

```text
standalone/default.env.local
standalone/.env.local
default.env.local
.env.local
```

Use `--env-file` to choose a different file explicitly. The selected env file is
read only on the host; it is never mounted into Docker.

The runner resolves the matching source files, mounts only those files, the
matching model directory, and the matching global schema. It runs pytest with
the selected physical identity:

```text
--datasource 2_1
DUALITY_SIM_DATASOURCE_VERSION=2_1
FHIR site inputs: DUALITY_CLIENT_SITE{1,2,3}_DATASOURCE_2_1
models path: /source-models/datasource_group_1
```

The test fixture keeps `2_1` as its direct-execution default, but uses
`setdefault`, so the runner-provided value wins. This is required for
datasource-group-specific FHIR configuration, including
`config/project_2/datasource_group_1/patient_query.json`. The copied job
template receives the selected datasource-specific global schema before pytest
stages individual jobs.

## Automatic model-pair discovery

Before Docker starts, the runner scans the selected model package for complete
pairs:

```text
{cox_lasso|logistic_reg}_{cancer_type}_weights.csv
{cox_lasso|logistic_reg}_{cancer_type}_cutoff.csv
```

It intersects those files with the test suite's known cancer/model matrix and,
by default, runs only those supported pairs across every sweep mode. No test
code is changed.

Eight suites are available via `--suite` (which tests run — independent of the
`--mode` lean/full axis above). Analyses: `lcs` = logistic
calibration statistics (meta-analysis), `km` = survival Kaplan-Meier biomarker
discovery, `combined` = KM AND LCS for one model in a single job (sharing one
score computation). Model versions: `open` = clear-text scoring, `enc` =
encrypted:

```text
lcs_open       LCS meta-analysis, clear-text scoring
lcs_enc        LCS meta-analysis, HE scoring
km_open        survival Kaplan-Meier biomarker discovery, clear-text scoring
km_enc         survival Kaplan-Meier biomarker discovery, HE scoring
combined_open  KM + LCS in one job (shared score), clear-text scoring
combined_enc   KM + LCS in one job (shared score), HE scoring
threshold      secure threshold-samples pre-pass, five fixed end-to-end cases
all (default)  the six sweeps above (the supported-pairs -k filter deselects the
               threshold and unit tests; run those via --suite threshold or with
               --pair-selection all)
```

### Secure threshold pre-pass suite (`--suite threshold`)

Five deterministic cases (not a per-cancer sweep) that run the protected
sample-count check (`workflow_threshold_samples_secure`) through the real
multiparty pipeline on the open-KM chain: pass verdicts at T=10 and T=20 (both
mask configs, masked-margin log lines asserted), forced extreme mask draws, and
the below-threshold stop (error.json codes + no downstream result). Two
TEST-ONLY env knobs in the client executor make single runs cover what would
otherwise be rare random draws:

* `DUALITY_SIM_THRESHOLD_MASK_Z=<total z>` pins the summed mask exponent (the
  per-site clip still applies). `27.14` is the draw that silently wrapped the
  decrypted sign before the two-tower fix carried by the bundled public snapshot wheel.
* `DUALITY_SIM_THRESHOLD_FORCE_COUNT=<n>` pins every site's local pre-count,
  standing in for a genuinely small cohort — only the general-statistics
  (project 1) pipeline produces those; the biomarker bundles never do.

The threshold verdict rides on CKKS decrypt headroom, so under lean's reduced
ring every case emits `ThresholdLeanModeWarning`: a lean pass does NOT certify
the production parameterization — run this suite once with `--mode full` before
relying on it for a release.

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --suite threshold
```

The threshold check has two more test layers outside this runner, both in
`tests/`: `test_threshold_samples.py` (fast unit tests: pre-pass argument
building plus the mask-parameter/headroom guard — plain `pytest`, no simulator)
and `threshold_mask_probe.py` (a standalone CKKS measurement script, not
collected by pytest, that re-derives the decrypt bound backing
`_THRESHOLD_SAFE_DECRYPT_BOUND` — run it after any CKKS parameter change).

Inspect the selected group first:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --datasource 2_1 --list-supported-pairs
```

Run every discovered supported case using an already-built image:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1
```

Run just open-access LCS cases:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --suite lcs_open
```

Run just the encrypted survival (Kaplan-Meier) cases:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --suite km_enc
```

Run one known pair:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --suite km_enc --keyword "Breast_Carcinoma and cox_lasso"
```

## Container-only datasource paths

A normal standalone env file may point at a container path such as
`/data/some-bundle.json`. The runner first checks the exact path, then tries the
same basename beneath `standalone/nvflare_stage/data`. Add a host search root
when the source files live elsewhere:

```bash
python tests/docker_simulator_runner/run_simulator_sweep.py --no-build --datasource 2_1 --data-root "C:\path\to\mskcc-data"
```

The runner stops instead of guessing when the basename maps to multiple files.

## Stale extracted bundles

Only the `.zip` archives under `standalone/nvflare_stage/data` are tracked, so a
data update arrives as a new archive beside an already-extracted `.json`. Before
mounting, the runner re-extracts any resolved JSON whose sibling ZIP is newer and
prints one line per refresh:

```
Refreshed Biomarker_..._testing_bundle_site1.json from Biomarker_..._testing_bundle_site1.zip (5177825 B archive was newer).
```

Nothing to run manually — pull the new archive and start the sweep. Same rule as
`client_utils/create_client.py`, so a sweep and a standalone deployment cannot
disagree about which bundle they are on. Extraction stamps the JSON with the
current time, so later runs are no-ops until the ZIP changes again.

## Results

What a result folder contains depends on `--mode`.

**lean (default)** — correctness only, kilobytes:

```text
pytest-output.txt           concise pytest status lines, including beta/p/max_delta details
pytest-status-events.jsonl  runner-only structured report events backing pytest-output.txt
junit.xml                   machine-readable final pytest outcome report
runner-datasource.json      physical datasource assignments and selected assets
supported-model-pairs.json  discovered complete/incomplete model artifacts
staged-global-schema.json   actual schema copied into the job template
```

**full** — adds the profiling + trace artifacts:

```text
performance-output.txt      stable per-case profile_summary.json timing, memory, and network metrics
performance-summary.json    machine-readable form of the same per-case metrics
full-console-output.txt     raw combined pytest, NVFlare, OpenFHE, and application output
taskflow/                   per-case trace diagrams + causal event traces (see below)
```

Lean writes no `performance-*`, no `full-console-output.txt`, and no `taskflow/`,
and it deletes each **passed** case's `simulator-workspaces/` entry as it finishes
(failed cases are kept for debugging).

The sweep container runs as root (it builds and installs the runtime wheel), but
hands ownership of everything under the results folder back to the host user on
exit — the runner passes your `id -u`/`id -g` as `DUALITY_HOST_UID`/`DUALITY_HOST_GID`
— so results, workspaces, and `taskflow/` can be read, regenerated, or deleted
without `sudo`.

`pytest-output.txt` mirrors the sweep's own verbose result details, such as
`PASSED [beta=... p=... max_delta=...]` and `SKIPPED [low SNR: ...]`, without
interleaved NVFlare/application logs.

### Survival details: near-cutoff binning

The encrypted and clear paths can legitimately disagree about a patient whose risk score sits
within `NEAR_CUTOFF_MARGIN` (1e-5) of the model cutoff, because the encrypted comparison
resolves that patient on CKKS noise rather than on the model. The `km`/`combined` suites
therefore report how the binning actually resolved, with the count of such patients:

```text
BINNING OK (<k> closer than 1e-05 to cutoff, <s> sites)   arms matched
REBINNED n=<j> (<k> closer than 1e-05 to cutoff, <s> sites)   j patients took the other arm
```

Read the verdict with the count: `REBINNED` with a non-zero count is the expected consequence
of an ambiguous cohort, `REBINNED` with a zero count is a defect. Only the count is retained —
never a margin or a score — and only the clear path can measure it, since it alone knows the
exact `score - cutoff`.

A consequence when diffing sweeps: a handful of near-cutoff cases legitimately flip verdict
between runs of the *same* configuration, so comparing failure **counts** across sweeps is
unreliable. Compare the failing **case set** against a baseline instead, and treat a case
outside that baseline as the real signal.


## Performance report (`--mode full`)

The following applies to `--mode full` only; lean mode writes none of it.

After pytest exits, the runner scans the ordinary per-party files already
written by the NVFlare profiler:

```text
simulator-workspaces/**/job-results/**/profile_summary.json
```

It leaves those raw files intact and creates two run-only artifacts:

```text
performance-output.txt      human-readable per-case, per-workflow, and per-phase metrics
performance-summary.json    same per-case metrics in stable machine-readable form
```

`performance-output.txt` deliberately does **not** calculate cross-case
averages, medians, percentiles, or totals. Cancer cohorts have very different
record counts, so those aggregates do not provide a meaningful performance
signal. Every timing, memory, and network value remains attached to its exact
test case, workflow, and phase for manual comparison with an equivalent prior
or future run.

Case wall time is the maximum `wall_time_sec` of the available server/client
profiles for that one case, because the simulated parties execute concurrently.
Compute and RTT are summed over profiled sites/workflows/rounds. Network is a
communication-workload indicator (sum of the site-local transmit and receive
counters), not literal physical wire traffic.

For a useful manual comparison, run the same datasource, supported pair set,
and host/Docker resource configuration. Background CPU load and image warmness
can still affect wall time.
## Taskflow traces (`--mode full`)

Alongside the timing summaries, each party's profiler now writes a timestamped
event stream (`trace.jsonl`) next to its `profile_summary.json`. After pytest,
the runner merges those per-party streams per test case into `taskflow/`:

```text
taskflow/<case>.perfetto.json  Chrome Trace Event format: one thread per party,
                               compute/dispatch/accept/aggregate/round spans (with
                               Lamport clocks), and flow arrows for correlated
                               task and result messages
taskflow/<case>.seq.mmd        Mermaid sequenceDiagram of the correlated messages
taskflow/<case>.lamport.dot    causal / Lamport space-time graph (Graphviz): one
                               column per party, events labelled with their Lamport
                               clock, message edges crossing columns
taskflow/<case>.timeline.svg   time swimlane: one column per party, y = elapsed time
                               (flowing down), compute/send/aggregate/background bars,
                               task/result arrows, and a max-party case-wall marker on
                               the time axis
taskflow/<case>.rounds.txt     per-round straggler + RTT decomposition table
taskflow/<case>.rounds.json    same, machine-readable
taskflow/index.md              per-case event/lane/span/message counts, the
                               correlation split (id vs fallback), causal depth,
                               and total/worst-round straggler wait
```

The `rounds` artifacts break each `(workflow, round)` into where its wall-clock
went: client idle-`wait` (polling before the task was ready), `fetch` (task
delivery), `compute`, and `send`, plus the **straggler gap** — how long the
server waited between the first and last client's result that round. The straggler
gap needs the server profiled (the sweep's `tests/sim_config_fed_server*.json`
now include the `profiler` component with `role: server`); without a server
profile, RTT still comes from the client cycles but the straggler gap reads 0.

Open a `.perfetto.json` in <https://ui.perfetto.dev> (or `chrome://tracing`) to
see the space-time timeline; render a `.seq.mmd` with any Mermaid viewer; render
the Lamport graph with `dot -Tsvg taskflow/<case>.lamport.dot -o <case>.svg`.

Messages are correlated by, in order: a per-message correlation id stamped on the
wire by `TraceCorrelationFilter` (registered in the sweep's server
`task_data_filters`); the NVFlare task id the profiler latches through each task
cycle; then a workflow + server-peer fallback that treats the round as a *soft*
preference. (Requiring an exact round match dropped the first server→client send
of every workflow — its client-side `task_recv` is tagged round `-1` before the
round is known — so the fallback now matches within the workflow and prefers the
same round only when the client side has a real one, restoring those initial
sends.) With the filter active every task-delivery and result message correlates
exactly by id; without it the task id and fallback still recover the arrows. The
filter also writes a
`trace_filter.jsonl` (server-side `dispatch_msg` records) that the emitter merges
in. Lamport and vector clocks are computed offline from the merged event DAG
(program order + message edges), so the causal ordering is correct without
synchronized clocks. When no messages can be correlated at all, the per-party
spans still render and only the arrows drop.

To regenerate these artifacts from an existing results folder without re-running
the sweep:

```bash
python build_taskflow_trace.py test-results/simulator-sweep-<stamp>
```

This runner is the test harness. The same trace + report also runs against the
real **standalone deployment** (distributed containers), where the profiler
always traces, each party's trace reaches the host via a site-namespaced copy in
the shared job-results mount, and the report is rendered host-side by
`taskflow_report.py` at result retrieval — not by this runner. Those containers
likewise hand ownership of their trace and report output back to the host user
(`DUALITY_HOST_UID`/`DUALITY_HOST_GID`, set automatically by `standalone/main.py`).

Case wall time is the maximum `wall_time_sec` of the available server/client
profiles for that one case, because the simulated parties execute concurrently.
Compute and RTT are summed over profiled sites/workflows/rounds. Network is a
communication-workload indicator (sum of the site-local transmit and receive
counters), not literal physical wire traffic.

For a useful manual comparison, run the same datasource, supported pair set,
and host/Docker resource configuration. Background CPU load and image warmness
can still affect wall time.
