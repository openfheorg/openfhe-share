import { deflate } from "pako";
import {
  decodeShareLaunchPayload,
  shouldAutoLoginFromLaunch,
} from "./LaunchPayload";

function encodePayload(payload: Record<string, unknown>): string {
  const compressed = deflate(JSON.stringify(payload));
  let binary = "";

  compressed.forEach((value) => {
    binary += String.fromCharCode(value);
  });

  return window
    .btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

describe("SHARE launch payloads", () => {
  test("decodes a direct-results launch and enables automatic login", () => {
    const payload = decodeShareLaunchPayload(
      encodePayload({
        v: 1,
        mode: "results",
        username: "initiator",
        nvflare_job_id: "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3",
      })
    );

    expect(payload.username).toBe("initiator");
    expect(payload.nvflare_job_id).toBe(
      "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
    );
    expect(shouldAutoLoginFromLaunch(payload)).toBe(true);
  });

  test("decodes an explore launch without enabling automatic login", () => {
    const payload = decodeShareLaunchPayload(
      encodePayload({
        v: 1,
        mode: "explore",
        username: "initiator",
      })
    );

    expect(payload.username).toBe("initiator");
    expect(payload.nvflare_job_id).toBeUndefined();
    expect(shouldAutoLoginFromLaunch(payload)).toBe(false);
  });

  test("keeps legacy v1 job links backward compatible", () => {
    const payload = decodeShareLaunchPayload(
      encodePayload({
        v: 1,
        username: "initiator",
        nvflare_job_id: "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3",
      })
    );

    expect(shouldAutoLoginFromLaunch(payload)).toBe(true);
  });

  test("rejects contradictory explore payloads", () => {
    expect(() =>
      decodeShareLaunchPayload(
        encodePayload({
          v: 1,
          mode: "explore",
          username: "initiator",
          nvflare_job_id: "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3",
        })
      )
    ).toThrow("must not contain an NVFlare job ID");
  });
});
