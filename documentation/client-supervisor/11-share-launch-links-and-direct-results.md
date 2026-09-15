# SHARE Launch Links and Direct Results

## Purpose

The SHARE Client desktop can open the SHARE web application in two ways:

- **Explore in SHARE** opens the normal login page with the current desktop username already filled in.
- **View These Results in SHARE** opens a specific completed NVFlare job, automatically performs the current development username lookup, and routes directly to the Results page.

This document defines the current launch-link contract across `client-supervisor`, the React frontend, and the backend. It also records what a production deployment would have to change. This version ships no authentication-provider integration and is not supported for production use.

## Current User Flows

### Explore in SHARE

The desktop sends a launch payload containing only the signed-in username:

```json
{
  "v": 1,
  "username": "initiator"
}
```

The frontend decodes the payload and prefills the username field on the normal login form. It does **not** automatically sign in because no NVFlare job ID is present.

### View These Results in SHARE

Each local job row uses the NVFlare job directory name as the job identifier. The desktop sends:

```json
{
  "v": 1,
  "username": "initiator",
  "nvflare_job_id": "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
}
```

The frontend decodes the payload, performs the current development login lookup using the included username, and enters the direct Results route for the supplied NVFlare-assigned job ID.

The `nvflare_job_id` value is the UUID used as the local job-results folder name and the backend `nvflare_jobs.nvflare_assigned_id` value. It is not the numeric MySQL row ID and not the job-runner UUID.

## Launch URL Wire Format

The launch payload is transported in one query parameter:

```text
?launch=<encoded-value>
```

The encoding steps are:

1. Build compact JSON using UTF-8.
2. Compress the JSON with a zlib-wrapped DEFLATE stream at compression level 6.
3. Encode the compressed bytes with URL-safe Base64.
4. Remove trailing Base64 `=` padding.
5. Add the value as the `launch` query parameter.

The Python implementation intentionally matches the browser's `pako.inflate()` behavior. Python's `zlib.compress(..., level=6)` produces the zlib-wrapped stream expected by pako's default inflate mode.

Example compact JSON before compression:

```text
{"v":1,"username":"initiator","nvflare_job_id":"54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"}
```

The generated URL preserves unrelated query parameters and fragments. Existing `launch`, `username`, and `nvflare_job_id` parameters are removed before the new `launch` parameter is appended.

This encoding is transport formatting only. It is not encryption, signing, authentication, or authorization. Anyone who receives the URL can decode the username and job ID.

## Client Supervisor Implementation

### Files

| File | Responsibility |
| --- | --- |
| `client-desktop/src/share_desktop/services/share_launch.py` | Validates the SHARE URL, constructs the payload, performs zlib/Base64URL encoding, preserves unrelated URL fields, and replaces stale launch fields. |
| `client-desktop/src/share_desktop/app_window.py` | Connects desktop buttons and job-row actions to the shared launch builder and opens the result in a new browser tab. |
| `client-desktop/tests/test_share_launch.py` | Verifies payload contents, UTF-8 round trips, pako-compatible compression, URL-safe unpadded Base64, URL preservation, stale-field replacement, and invalid-input handling. |

### Shared Builder

`encode_share_launch_payload(username, nvflare_job_id=None)` always requires a non-empty username. It adds `nvflare_job_id` only when a non-empty job ID is supplied.

`build_share_launch_url(share_url, username, nvflare_job_id=None)` requires an absolute HTTP or HTTPS URL and returns one URL containing exactly one current `launch` parameter.

### Desktop Actions

`DualityClientWindow._open_share_launch()` requires an active desktop session and uses `self.session.username` as the username source.

| Desktop Action | Job ID Argument | Result |
| --- | --- | --- |
| `Explore in SHARE` | `None` | Username-only payload; frontend login form is prefilled. |
| `View These Results in SHARE` | Local top-level job directory name | Username and NVFlare job ID payload; frontend performs the current direct-results login flow. |

The desktop does not accept an arbitrary username or site for these actions. It uses the username already returned by the desktop `/user/role` session lookup.

The SHARE destination is configured through the `[share]` section in `client-desktop/share-client.ini` and can be changed in desktop Settings. The selected value is retained in `~/.duality-client/desktop-state.json`.

## Frontend Implementation

### Launch Decoding

`src/utils/LaunchPayload.ts`:

1. Converts Base64URL characters back to standard Base64.
2. Restores required padding.
3. Decodes to compressed bytes.
4. Calls `pako.inflate()`.
5. Decodes UTF-8 JSON.
6. Validates payload version, username, optional job ID, and optional mode.

Version 1 payloads without an explicit `mode` remain supported:

- username only means Explore/prefill
- username plus `nvflare_job_id` means direct Results/automatic login

### URL Cleanup

`src/App.tsx` reads the launch payload only during initial application setup. It then removes `launch`, `username`, and `nvflare_job_id` from the visible URL with `history.replaceState()` so the payload is not left in the address bar after initialization.

The application stores the direct job ID in React state and browser history state so back/forward navigation can restore the Results screen without re-exposing the launch payload in the URL.

### Login Behavior

`src/pages/LoginPage.tsx` still calls:

```http
POST /user/role
```

with:

```json
{
  "username": "initiator"
}
```

For Explore links, the username field is prefilled and the user remains on the login form.

For direct Results links, `LoginPage` performs the same username lookup automatically. This is why the current prototype appears to bypass login. It bypasses the login **screen**, not backend authentication, because `/user/role` is currently only a username-based role lookup.

### Direct Results Bootstrap

After the automatic username lookup succeeds, `App.tsx` renders `ResultsPage` with:

- `nvflareJobId`
- `directEntry`
- the base user session
- an `onContextLoaded` callback used to hydrate the selected project and datasource context

The page title and navigation are then rendered from the project returned by the backend context lookup.

## Backend Direct-Results Bootstrap

Direct launch uses:

```http
POST /nvflare/jobs/results_context
Content-Type: application/json
```

Request:

```json
{
  "nvflare_job_id": "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
}
```

The route:

1. Resolves the job with `NVFlareJobsManager.get_nvflare_job_by_assigned_id()`.
2. Loads the referenced project, including the job's datasource-group context.
3. Loads the saved filter when the job has a `filter_id`.
4. Returns compact job metadata, project metadata, and the saved filter.

Response shape:

```json
{
  "status": "SUCCESS",
  "job": {},
  "project": {},
  "filter": {}
}
```

The compact job summary includes normal Job Summary fields only:

- status and timestamps
- run duration
- datasource group
- party participation overrides
- function names

Workflow settings, threshold settings, and crypto-audit details are intentionally excluded from this bootstrap response and from Job Summary.

Workflow mapping and result bodies remain lazy-loaded through the existing result endpoints after context is established:

```text
POST /jobs/results/mapping
POST /jobs/results
POST /jobs/function/config   # fallback only
```

Normal Job History navigation does not use `results_context`. It already has project, filter, and row context, so it continues to use `/jobs/info` before loading workflow mappings and results. Both entry paths converge on the same `ResultsPage` rendering and lazy result-loading logic.

## Current Security Boundary

The current launch-link implementation is a development convenience and must not be treated as production single sign-on.

Current limitations:

- The payload contains a plain username and optional job UUID after reversible compression/encoding.
- `/user/role` trusts the submitted username and does not validate a password, JWT, or signed identity claim.
- `/nvflare/jobs/results_context` currently does not verify that the caller is authorized to view the requested job or project.
- Possession of a job UUID is not authorization.
- Query parameters can appear in browser history, intermediary logs, screenshots, support captures, and referrer data before the frontend removes them.

The current direct-results flow therefore bypasses only the prototype login UI. It does not establish a cryptographically authenticated user session.

## Required Changes Before Production Use

Before any production use, the launch contract must stop trusting `username` as proof of identity. This requires an identity provider, which this version does not include.

The preferred production pattern is an opaque, short-lived launch code rather than placing an identity token or access token directly in the URL.

### Recommended Flow

1. The user authenticates the SHARE Client desktop through the identity provider.
2. The desktop calls an authenticated backend launch-token endpoint.
3. The backend verifies the authenticated principal and confirms access to the requested project/job.
4. The backend issues a short-lived, narrowly scoped, preferably single-use launch code.
5. The desktop opens SHARE with `?launch=<opaque-code>`.
6. The frontend exchanges the code with the backend.
7. The backend validates and consumes the code, then establishes the normal browser application session and returns the authorized destination context.
8. The frontend removes the launch code from the visible URL immediately.

### Token/Code Claims and Binding

The server-side launch record or signed token should bind at least:

- authenticated subject identifier (`sub`)
- application username/user ID mapping
- action or scope: `explore` or `view_results`
- optional NVFlare job ID for `view_results`
- authorized project/site context as needed
- issued-at time
- short expiration time
- unique nonce or token ID for replay protection

For a Results launch, the backend must verify that the authenticated principal is authorized to view the specific job. The browser must not be allowed to replace the job ID after the code is issued.

### Why Not Put Identity Tokens in the URL

Raw identity/access tokens should not be carried as query parameters because URLs are routinely copied and recorded. An opaque one-time code limits exposure and can be revoked or consumed without exposing the underlying token.

### Explore Behavior With Real Authentication

`Explore in SHARE` should use the existing authenticated browser session when available. If no browser session exists, it should enter the normal sign-in flow. A launch code may still carry a post-login destination hint, but username prefill should no longer be the trust mechanism.

### Results Behavior With Real Authentication

`View These Results in SHARE` should preserve the current one-click experience, but automatic navigation must occur only after the launch code is exchanged and the backend authorizes the user/job relationship.

## Validation and Acceptance Criteria

The current implementation is covered by `client-desktop/tests/test_share_launch.py`.

Expected behavior:

| Scenario | Expected Result |
| --- | --- |
| Explore action while signed in to the desktop | Browser opens SHARE with a version-1 username-only payload; login form is prefilled. |
| View action for a local job UUID | Browser opens SHARE with username and exact job-folder UUID; frontend performs the development auto-login and loads that Results page. |
| Existing SHARE URL contains `s=0` or another unrelated parameter | Parameter is preserved. |
| Existing SHARE URL contains stale `launch`, `username`, or `nvflare_job_id` | Stale fields are removed and replaced by one current `launch` value. |
| Unicode username | JSON/UTF-8/pako round trip preserves the username. |
| Missing username or invalid SHARE URL | Desktop reports an error and does not open the browser. |
| Unknown job UUID | `results_context` returns not found and ResultsPage displays a load error. |
