# Startup-Kit Delivery and Managed Workspace

## Shared Delivery Module

`startup_kit_delivery.py` implements the common terminal-side startup-kit workflow. The desktop has a corresponding service and runner using the same contract.

## Backend Contract

The client sends:

```http
POST /clients/content/startup-kit
Content-Type: application/json
Accept: application/gzip
```

Request:

```json
{
  "client_name": "site1"
}
```

A successful response is binary `tar.gz` content with headers including:

```text
Content-Type: application/gzip
Content-Disposition: attachment; filename="share-client-site1-startup-kit.tar.gz"
X-SHARE-Client-Site: site1
X-SHARE-Artifact-SHA256: <sha256>
X-SHARE-Artifact-Size: <bytes>
```

Backend errors remain JSON HTTP responses.

## Download Location

Archives are streamed to a `.part` file and then atomically renamed under:

```text
~/.duality-client/inbox/share-client-<site>-startup-kit.tar.gz
```

The incomplete file is removed when download or validation fails.

## Validation

Before installation, the supervisor verifies:

- the site name matches a conservative identifier pattern
- the archive is non-empty
- the backend SHA-256 header matches when present
- the archive contains exactly one top-level site folder
- the top-level folder matches the requested site
- `<site>/startup/start.sh` exists
- no archive member escapes the staging directory
- no symlink or hard-link entry is accepted
- only regular files and directories are extracted

## Managed Installation

The default installation base is:

```text
~/.duality-client
```

The resulting workspace is:

```text
~/.duality-client/<site>
```

Installation uses a temporary staging directory under the managed base. The supervisor does not extract directly over the active workspace.

When the target already exists:

1. The current workspace is renamed to a timestamped backup.
2. The staged replacement is moved into the canonical site path.
3. If the move fails, the previous workspace is restored when possible.

Backup example:

```text
~/.duality-client/site1.backup-20260720-141500
```

The installer always creates:

```text
~/.duality-client/<site>/job-results
```

## Why Tar Is Required

NVFlare startup kits rely on signed content and Unix file metadata. The workflow uses tar rather than zip so executable modes and other normal tar metadata are retained.

For the deployed backend, the archive is created directly on the Linux NVFlare EC2 host before it is transferred to the API container. This avoids reconstructing the archive from a filesystem that may flatten permissions.

## Backend Local and Remote Behavior

| Backend environment | Packaging behavior |
| --- | --- |
| `SHARE_ENV=local` | Read and tar the locally available NVFlare workspace. Permission normalization handles Windows-mounted all-`0777` trees when detected. |
| Any non-local environment | SSH to the configured NVFlare EC2 host, validate the requested site, create the tar on Linux, atomically publish the stable site archive, and download it through SFTP. |

The stable remote archive is kept at:

```text
<remote-workspace>/tar_files/<site>.tar.gz
```

Each request builds a unique temporary archive before replacing the stable path, preventing partial downloads.

## API Overrides

The common delivery module resolves the backend base in this order:

1. explicit function or CLI argument
2. `DUALITY_CONTENT_API_BASE_URL`
3. `DUALITY_BACKEND_URL`
4. default AWS API base

The endpoint path can be overridden with:

```text
DUALITY_STARTUP_KIT_PATH
```
