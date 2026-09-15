import { inflate } from "pako";

export const SHARE_LAUNCH_PAYLOAD_VERSION = 1;

export type ShareLaunchMode = "explore" | "results";

export interface ShareLaunchPayload {
  v: typeof SHARE_LAUNCH_PAYLOAD_VERSION;
  username: string;
  nvflare_job_id?: string;
  mode?: ShareLaunchMode;
}

function decodeBase64Url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const paddingLength = (4 - (normalized.length % 4)) % 4;
  const binary = window.atob(normalized.padEnd(normalized.length + paddingLength, "="));
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

function requireNonEmptyString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Launch link does not contain a valid ${fieldName}`);
  }

  return value.trim();
}

export function decodeShareLaunchPayload(value: string): ShareLaunchPayload {
  const compressed = decodeBase64Url(requireNonEmptyString(value, "payload"));
  const decompressed = inflate(compressed);
  const parsed = JSON.parse(new TextDecoder("utf-8").decode(decompressed)) as unknown;

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Launch payload is invalid");
  }

  const payload = parsed as Record<string, unknown>;
  const version = payload.v ?? SHARE_LAUNCH_PAYLOAD_VERSION;

  if (version !== SHARE_LAUNCH_PAYLOAD_VERSION) {
    throw new Error(`Unsupported launch-link version: ${String(version)}`);
  }

  const username = requireNonEmptyString(payload.username, "username");
  const jobId =
    payload.nvflare_job_id == null
      ? undefined
      : requireNonEmptyString(payload.nvflare_job_id, "NVFlare job ID");

  let mode: ShareLaunchMode | undefined;
  if (payload.mode != null) {
    if (payload.mode !== "explore" && payload.mode !== "results") {
      throw new Error("Launch payload contains an unsupported mode");
    }
    mode = payload.mode;
  }

  if (mode === "results" && !jobId) {
    throw new Error("Results launch link does not contain an NVFlare job ID");
  }
  if (mode === "explore" && jobId) {
    throw new Error("Explore launch link must not contain an NVFlare job ID");
  }

  return {
    v: SHARE_LAUNCH_PAYLOAD_VERSION,
    username,
    ...(jobId ? { nvflare_job_id: jobId } : {}),
    ...(mode ? { mode } : {}),
  };
}

export function shouldAutoLoginFromLaunch(payload: ShareLaunchPayload | null): boolean {
  if (!payload) {
    return false;
  }

  if (payload.mode) {
    return payload.mode === "results";
  }

  // Backward compatibility with v1 payloads created before an explicit mode
  // was added: a job ID means direct results; username-only means prefill.
  return Boolean(payload.nvflare_job_id);
}
