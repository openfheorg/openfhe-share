# NVFlare Admin, Server, and SSH Integration

## Files Covered

| File | Role |
| --- | --- |
| `app/core/nvflare/NVFlareAdminKitManager.py` | Loads the NVFlare admin kit, extracts it into the backend container, and runs `fl_admin.sh` commands through `pexpect`. |
| `app/core/nvflare/NVFlareClientSnapshot.py` | Uses the admin kit to run `check_status server`, parses NVFlare client rows, and merges the live NVFlare view with registered clients from MySQL. |
| `app/core/nvflare/NVFlareServerProvider.py` | Provides environment-specific NVFlare workspace paths and job-result locations. |
| `app/core/ssh/SSHConnectionProvider.py` | Provides pooled SSH/SFTP access for non-local environments. |
| `app/core/aws/ResourceConfigProvider.py` | Supplies the non-local EC2 SSH host/user/key path used by `SSHConnectionProvider`. |
| `app/core/job_runner/job_tasks/NVFlareJobTask.py` | Verifies non-local SSH connectivity before staging/submitting a standard analytics job. |
| `app/core/job_runner/job_tasks/NVFlareParticipationJobTask.py` | Verifies non-local SSH connectivity before staging/submitting a participation confirmation job. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobRunner.py` | Submits staged jobs through the NVFlare admin kit with `submit_job`. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobMonitor.py` | Polls job state through the NVFlare admin kit with `list_jobs`. |
| `app/core/job_runner/nvflare_jobs/NVFlareJobUploader.py` | Deprecated SSH upload implementation retained in the codebase but not used by the current standard job path. |
| `app/core/mysql/job_tracking/NVFlareJobsDataRetriever.py` | Reads completed result files locally in `LOCAL`, or over SSH in non-local environments. |

## Integration Model

The current backend uses two separate integration paths for NVFlare operations:

| Integration path | Current use |
| --- | --- |
| NVFlare admin kit via `fl_admin.sh` | Current path for client status snapshots, job submission, and job monitoring. |
| SSH/SFTP via Paramiko and OpenSSH | Connectivity verification in non-local job flows and remote result-file reads in non-local result retrieval. |

The active job submission path does not upload a zip through SSH. `NVFlareJobStager` builds a staged job directory on the backend filesystem, and `NVFlareJobRunner` submits that directory by calling `submit_job <absolute_job_path>` through `fl_admin.sh`.

## NVFlare Admin Kit Manager

`NVFlareAdminKitManager` is the central helper for all active `fl_admin.sh` operations.

### Runtime Paths and Environment Variables

| Value | Source | Behavior |
| --- | --- | --- |
| Admin extraction base | Constant `BASE_DIR = "/app/nvflare/admin"` | Extracted admin kits are stored under this container path. |
| Startup subdirectory | Constant `STARTUP_SUBDIR = "startup"` | The manager expects the extracted admin home to contain `startup/fl_admin.sh`. |
| Admin script | Constant `ADMIN_SCRIPT = "fl_admin.sh"` | All admin commands are executed through this script. |
| Admin tar path | `DUALITY_ADMIN_TAR` | Required. In `LOCAL`, this is a local tar/tar.gz path. In non-local environments, this is an S3 URI. |
| Admin username | `DUALITY_NVFLARE_ADMIN_NAME` | Optional unless `fl_admin.sh` prompts for a user name. If prompted, the manager sends this value. |
| AWS region | `AWS_REGION`, `AWS_DEFAULT_REGION`, default `us-east-1` | Used to create the S3 client for non-local admin kit download. |

If `DUALITY_ADMIN_TAR` is missing, `NVFlareAdminKitManager.__init__()` raises `ValueError("DUALITY_ADMIN_TAR is not set")`. This affects any endpoint or job path that creates `NVFlareAdminKitManager`, including client connection status, job submission, and job monitoring.

### Local and Non-Local Admin Kit Loading

`NVFlareAdminKitManager` branches on `EnvironmentProvider.get_env()`:

| Environment | Admin kit source | Change detection |
| --- | --- | --- |
| `LOCAL` | Local file path from `DUALITY_ADMIN_TAR` | SHA-256 of file size and integer mtime. |
| Non-local | S3 object from `DUALITY_ADMIN_TAR` | S3 object ETag from `head_object`. |

The manager stores the last extracted token in `/app/nvflare/admin/.etag`. On each run, `_ensure_ready()` compares the current token to the stored token. If the token changed, it cleans the extraction directory and extracts the new kit.

Archive extraction is guarded against path traversal. `_extract_archive()` resolves every tar member destination and refuses to extract any member outside the target directory.

After extraction, `_resolve_admin_home()` finds the first child directory that contains `startup/fl_admin.sh`. `_harden_script()` sets the execute bit and normalizes CRLF line endings to LF.

### Running Admin Commands

`run(commands: List[str], timeout: int = 300) -> Tuple[int, str]` performs the current admin command execution flow:

1. Calls `_ensure_ready()` so the admin kit is available and current.
2. Starts `fl_admin.sh` with `pexpect.spawn()` from the extracted admin home’s `startup` directory.
3. Waits for either the admin prompt, a username prompt, EOF, or timeout.
4. Sends `DUALITY_NVFLARE_ADMIN_NAME` if a username prompt appears.
5. Sends each requested command and waits for the next prompt.
6. Sends `bye` and waits for EOF.
7. Returns the process exit status and normalized console output.

Output normalization removes ANSI escape sequences, converts CRLF/CR to LF, strips trailing whitespace from lines, and returns a trimmed string.

If the console closes or times out before the prompt, or while a command is running, the manager closes the child process and returns exit code `1` with an `[fl_admin] Aborted: ...` message in the output.

## NVFlare Client Snapshot

`NVFlareClientSnapshot` is used by client-state endpoints and participation logic to obtain the current NVFlare server/client view.

### Call Sites

| Caller | Behavior |
| --- | --- |
| `POST /clients/connection/status` in `ClientRoutes.py` | Returns the live connection snapshot to the frontend. |
| `POST /clients/participation/status` in `ClientRoutes.py` | Optionally includes the live connection snapshot before overlaying participation status. |
| `NVFlareParticipationJobTask.get_participation_client_list()` | Uses a snapshot to decide which clients are pending, accepted, or available for a job. |

### Snapshot Flow

`get_clients(username: Optional[str] = None)` performs this sequence:

1. Runs `check_status server` through `NVFlareAdminKitManager.run()` with a 20-second timeout.
2. Parses the NVFlare output table using `CLIENT_ROW_RE`.
3. Builds a synthetic server row named `Server`.
4. Uses `ParticipationManager.clients_list()` to load MySQL-registered clients.
5. Uses `ParticipationManager.get_all_initiator_client_names()` to mark initiator clients.
6. If `username` was supplied, uses `ParticipationManager.get_client_names_for_username(username)` to mark submitted-user clients.
7. Marks live NVFlare clients as registered when they are present in MySQL.
8. Adds registered MySQL clients that were missing from the NVFlare output with `last_connect_time = "0"`.

### Returned Client Fields

The returned client dictionaries can include:

| Field | Meaning |
| --- | --- |
| `client_name` | NVFlare/MySQL client name. |
| `last_connect_time` | Raw NVFlare last-connect value, `SERVER_ONLINE`, or `0` when unavailable/offline/missing. |
| `registered` | Whether the client is known in the backend MySQL client roster. |
| `is_server` | Present and `true` only for the synthetic server row. |
| `server_online` | Present on the server row. `true` only when `check_status server` returned exit code `0`. |
| `connection_error` | Present when the server check failed or raised an exception. |
| `is_initiator` | Present and `true` when the client is marked as an initiator in MySQL. |
| `is_submitted_user` | Present and `true` when the supplied username maps to that client. |

When `check_status server` raises an exception, the snapshot still returns a server row. The server row has `last_connect_time = "0"`, `server_online = false`, and a `connection_error` string. The method still attempts to merge in MySQL-registered clients after the failed admin call.

## NVFlare Server Provider

`NVFlareServerProvider.py` defines:

| Type | Role |
| --- | --- |
| `NVFlareProvision` | Dataclass containing NVFlare workspace and result path settings. |
| `NVFlareProvisionProvider.get_nvflare_instance()` | Returns an `NVFlareProvision` for the current environment. |

### `NVFlareProvision` Fields

| Field | Meaning |
| --- | --- |
| `base_location` | Base NVFlare workspace path. |
| `admin_location` | Admin kit workspace path. |
| `server_location` | Server workspace path. |
| `client_to_server_job_save_location` | Directory where server-side job output is expected. |

### Local Provisioning

For `Environment.LOCAL`, `get_nvflare_instance()` uses environment variables with defaults:

| Value | Source |
| --- | --- |
| Host | `DUALITY_NVFLARE_HOST`, default `127.0.0.1`. |
| Workspace base | `DUALITY_NVFLARE_WORKSPACE`, default `./nvflare_workspace`, resolved to an absolute path. |
| Job save location | `DUALITY_NVFLARE_JOB_SAVE_LOCATION`, or `<workspace>/job-results` if unset. |
| Admin location | `<workspace>/admin@share.local`. |
| Server location | `<workspace>/<host>`. |

### DEV Provisioning

For `Environment.DEV`, `get_nvflare_instance()` returns hardcoded paths:

| Field | DEV value |
| --- | --- |
| `base_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00` |
| `admin_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/admin@share.local` |
| `server_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/nvflare.example.org` |
| `client_to_server_job_save_location` | `/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00/site3/job-results` |

The current implementation only explicitly returns provisioning for `LOCAL` and `DEV`.

## SSH Connection Provider

`SSHConnectionProvider` provides pooled Paramiko SSH clients plus SFTP upload and pexpect-based interactive SSH support.

### Configuration Source

`SSHConnectionProvider.__init__()` calls `ResourceConfigProvider.get_nvflare_ec2_ssh_config(check_cached=False)`.

Current resource configuration is:

| Environment | Host | Username | Port | Private key path |
| --- | --- | --- | --- | --- |
| `LOCAL` | empty string | empty string | `22` | empty string |
| `DEV` | `nvflare.example.org` | `ubuntu` | `22` | `/app/keys/nvflare.pem` |

The SSH provider is only created by current job/result flows in non-local environments. Local flows avoid SSH and use local filesystem paths.

### Private Key Handling

`_ensure_key_file()` checks whether `self.pem_path` already exists. If it does not exist, it fetches the secret named `nvflare/ssh_key` from AWS Secrets Manager in `AWS_REGION` or `us-east-1`, writes the secret string to the key path, creates the parent directory if needed, and sets file permissions to `0400`.

Expected secret shape:

```text
SecretId: nvflare/ssh_key
SecretString: raw PEM private key content
```

The current SSH helper expects the secret string itself to be the private key content. It does not parse a JSON object for this secret.

### Pooling Behavior

`SSHConnectionProvider` is a singleton accessed through `get_instance()`. The singleton uses a thread lock during first construction.

The instance builds a queue-backed pool of up to five SSH clients. `get_connection()` retrieves a pooled connection, checks that the transport is active and authenticated, closes stale connections, and creates a new connection when the pool is empty. `release_connection()` returns active connections to the pool or closes them if the pool is full or inactive.

`rebuild_pool()` closes all currently pooled connections and rebuilds the initial pool.

### Non-Interactive Commands

`run(command: str, timeout: int = 600, retries: int = 2)` executes a remote command using Paramiko `exec_command()`. It returns `(code, stdout, stderr)`.

On `paramiko.SSHException`, `EOFError`, `OSError`, or socket errors, it retries with a short exponential sleep. After retries are exhausted, it returns exit code `1`, empty stdout, and an error string beginning with `SSH unavailable after reconnect attempts:`.

### Interactive Commands

`run_interactive(remote_cmd: str, expect_send_pairs: list, timeout: int = 60)` uses `/usr/bin/ssh` through `pexpect`. It:

1. Quotes the private key path.
2. Ensures `/app/known_hosts` exists when possible.
3. Runs SSH with `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile`, and `LogLevel=ERROR`.
4. Applies each `(pattern, response)` pair using `expect()` and optional `sendline()`.
5. Reads remaining output before closing the child process.

This method returns the captured output string. Current active job submission and monitoring use `NVFlareAdminKitManager`, not this interactive SSH method.

### Uploads

`upload(local_path: str, remote_path: str, retries: int = 2)` uploads a local file through SFTP. `_mkdirs()` creates the remote directory path before upload. On retryable SSH/socket errors, it retries and then raises `RuntimeError` if all attempts fail.

The current standard job submission path does not call `upload()`. Remote result lookup uses `run()` with commands such as `cat` and `find`.

## Current Standard Job Submission Flow

The active standard analytics job path is:

1. `NVFlareJobTask.run_nvflare_job()` receives a job request from `JobRunnerService`.
2. In non-local environments, it creates `SSHConnectionProvider.get_instance()` and runs `hostname && uptime` to verify remote SSH connectivity.
3. It gets environment-specific NVFlare paths from `NVFlareProvisionProvider.get_nvflare_instance()`.
4. It records the internal job entry through `NVFlareJobsManager`.
5. It runs the participation confirmation flow through `NVFlareParticipationJobTask`.
6. It stages the analytics job directory through `NVFlareJobStager.stage_job()`.
7. It stores the staged job path through `NVFlareJobsManager.set_nvflare_job_path()`.
8. It creates `NVFlareJobRunner` and calls `run_job()`.
9. `NVFlareJobRunner` runs `submit_job <absolute_staged_job_path>` through `NVFlareAdminKitManager.run()`.
10. `NVFlareJobRunner` parses the NVFlare-assigned UUID from admin output using `ASSIGNED_ID_RE`.
11. It computes the output path as `<client_to_server_job_save_location>/<assigned_job_id>`.
12. It stores the NVFlare-assigned ID and output path through `NVFlareJobsManager`.
13. It creates `NVFlareJobMonitor` and calls `wait_for_completion()`.
14. `NVFlareJobMonitor` polls `list_jobs <assigned_job_id>` through `NVFlareAdminKitManager.run()` until the parsed status begins with `FINISHED:` or the monitor times out.

The admin kit path is therefore required for both job submission and monitoring.

## Participation Job Flow

`NVFlareParticipationJobTask` uses the same integration pieces as the standard job flow:

1. It calls `NVFlareClientSnapshot().get_clients()` to collect the server/client view.
2. It records or checks pending participation in MySQL.
3. If all required clients are already accepted, it skips broadcasting and returns the accepted client list.
4. If any clients need confirmation, it verifies SSH connectivity in non-local environments with `hostname && uptime`.
5. It stages the `participation_confirmation` job through `NVFlareJobStager`.
6. It submits the participation job through `NVFlareJobRunner`, which calls `submit_job` through `fl_admin.sh`.
7. It polls MySQL participation state until all clients respond or the response window expires.
8. It returns only accepted clients for downstream analytics job construction.

The participation flow submits an NVFlare job, but its monitoring loop is based on backend MySQL participation state rather than `NVFlareJobMonitor.wait_for_completion()`.

## Job Monitoring Through Admin Kit

`NVFlareJobMonitor` uses `NVFlareAdminKitManager` directly.

| Method | Behavior |
| --- | --- |
| `_parse_list_jobs_row(text)` | Parses `list_jobs` table rows into `job_id`, `name`, `status`, `submit_time`, and `run_duration`. |
| `_loop_body_parse_and_update(out_text)` | Finds the current job row, updates NVFlare status and submission timing through `NVFlareJobsManager`, and returns finished state when status starts with `FINISHED:`. |
| `wait_for_completion(poll_interval=2, timeout=900)` | Polls `list_jobs <job_id>` until terminal status or timeout. |

In the standard job task, `wait_for_completion()` is called with `poll_interval=10` and `timeout=600`.

If an admin command returns non-zero during monitoring, the monitor treats it as transient, sleeps, and retries. If the timeout expires, it raises `TimeoutError` with the last status value.

## Result Retrieval and SSH

`NVFlareJobsDataRetriever` reads completed result payloads after a job has run.

| Environment | Result access behavior |
| --- | --- |
| `LOCAL` | Reads JSON files directly from the local filesystem. |
| Non-local | Creates `SSHConnectionProvider.get_instance()` and reads remote JSON files with SSH commands. |

The retriever uses `NVFlareProvisionProvider.get_nvflare_instance()` and function-to-computation mappings to locate result folders. Remote reads use commands such as:

```text
cat <remote_path>
find <client_dir> -mindepth 1 -maxdepth 1 -type d
```

Result lookup prefers `raw_results.json` over `results.json` for initiator results, also checks client-site `error.json`, local fallback files, aggregated results, processed aggregated results, and workflow-level errors.

## Deprecated Uploader

`NVFlareJobUploader.py` is marked with `#DEPRECATED CLASS` and its operational methods are commented out. The retained code shows an older path that zipped job folders, uploaded them over SSH/SFTP, unzipped them remotely, and returned the remote job directory.

The current standard path does not use this uploader. Current staging returns a local staged directory that `fl_admin.sh submit_job` can submit directly.

## Authentication and Security Assumptions

| Area | Current behavior |
| --- | --- |
| Admin kit access | Depends on `DUALITY_ADMIN_TAR` and the extracted `startup/fl_admin.sh`. Non-local mode downloads the tar from S3. |
| Admin username | Sent only if the admin console prompts for a username. Value comes from `DUALITY_NVFLARE_ADMIN_NAME`. |
| SSH key | Pulled from Secrets Manager secret `nvflare/ssh_key` if `/app/keys/nvflare.pem` does not already exist. |
| SSH host key | Interactive SSH uses `StrictHostKeyChecking=accept-new`. Paramiko uses `AutoAddPolicy()`. |
| Client status endpoint protection | `ClientRoutes.py` contains `# Put behind bearer token` comments, but the route definitions themselves do not enforce bearer-token validation in this backend code. |
| Admin command output | The backend logs raw `submit_job` output to stdout in `NVFlareJobRunner`. |

## Failure Modes and Troubleshooting

| Symptom | Likely source | Backend behavior |
| --- | --- | --- |
| `DUALITY_ADMIN_TAR is not set` | Missing admin kit configuration | `NVFlareAdminKitManager` construction fails. Client status, job submit, and job monitor flows that need admin commands fail. |
| Local admin tar file not found | Invalid local `DUALITY_ADMIN_TAR` path | `_current_token()` raises `FileNotFoundError`. |
| Invalid S3 admin tar URI | Non-local `DUALITY_ADMIN_TAR` is not `s3://bucket/key` | `_parse_s3_uri()` raises `ValueError`. |
| S3 admin tar missing or inaccessible | Bad bucket/key, IAM, or region | `_current_token()` returns an empty token on `head_object` `ClientError`; download can still fail in `_download_and_extract_s3()`. |
| `startup/fl_admin.sh not found after extraction` | Tar layout does not contain an admin home with `startup/fl_admin.sh` | `_ensure_ready()` raises `RuntimeError`. |
| Admin script not found at resolved path | Extracted layout changed or incomplete | `_ensure_ready()` raises `FileNotFoundError`. |
| Admin console timeout before prompt | `fl_admin.sh` did not start correctly or server/admin context is unavailable | `run()` returns exit code `1` with an aborted message. |
| `submit_job` returns non-zero | NVFlare admin command failed | `NVFlareJobRunner.run_job()` raises `RuntimeError` with the admin output. |
| Assigned job ID cannot be parsed | `submit_job` output format changed or submission failed without a recognized UUID line | `NVFlareJobRunner.run_job()` raises `RuntimeError`. |
| Job monitor never sees `FINISHED:` | NVFlare job remains active, fails to appear in `list_jobs`, or output format changed | `NVFlareJobMonitor.wait_for_completion()` raises `TimeoutError`. |
| SSH key secret missing | `nvflare/ssh_key` absent or inaccessible | `_ensure_key_file()` raises during SSH provider construction. |
| SSH private key secret empty | Secret exists but has no `SecretString` | `_ensure_key_file()` raises `RuntimeError("SSH private key secret is empty")`. |
| SSH unavailable | EC2 host, network, key, or auth issue | `run()` returns code `1` and an `SSH unavailable after reconnect attempts` error string after retries. |
| Remote result JSON unreadable | Missing file, bad path, SSH failure, or invalid JSON | `NVFlareJobsDataRetriever` returns an error payload for that file/result section. |

## Operational Notes

- `DUALITY_ADMIN_TAR` is mandatory for active NVFlare admin operations.
- In `LOCAL`, job paths and result paths are filesystem paths inside or mounted into the backend runtime.
- In non-local environments, SSH is still required for connectivity verification and result retrieval even though job submission itself uses the admin kit.
- `NVFlareProvisionProvider` currently has explicit provisioning for `LOCAL` and `DEV`; additional environments need explicit returns before they can use this provider safely.
- The route comments indicate bearer-token protection is intended for client-state endpoints, but the current backend route functions do not implement that check directly.


## Startup-Kit Content Delivery over SSH

`ClientStartupKitDeliveryService` reuses `NVFlareProvisionProvider` and `SSHConnectionProvider` when `SHARE_ENV` is not `local`.

Remote flow:

1. Resolve the environment-specific NVFlare workspace and EC2 SSH configuration.
2. Validate `<workspace>/<client_name>` and its `startup` folder.
3. Create a unique temporary tar under `<workspace>/tar_files` on the EC2 host.
4. Publish a stable `<workspace>/tar_files/<client_name>.tar.gz` only after the tar command succeeds.
5. Download the exact temporary tar to the API container through `SSHConnectionProvider.download()`.
6. Compute SHA-256 and return the archive through `FileResponse`.
7. Remove request-specific temporary remote files and the API container's temporary copy while retaining the stable remote archive.

The archive is created on Linux so source permissions and executable bits are retained. The command excludes `__pycache__`, `*.pyc`, and `*.pyo`.

`SSHConnectionProvider.download()` uses SFTP with pooled SSH connections and retry handling matching the existing upload/run patterns.
