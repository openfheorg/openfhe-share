import { getWorkflowErrorFromJobData, getWorkflowWarning, WARN_EXCEPTION_MARKER } from "./WorkflowErrorPanel";

describe("getWorkflowErrorFromJobData", () => {
  test("reads supported error property aliases", () => {
    expect(getWorkflowErrorFromJobData({ workflowError: { message: "boom" } })).toEqual({ message: "boom" });
    expect(getWorkflowErrorFromJobData({ error_json: "serialized failure" })).toEqual({ message: "serialized failure" });
  });

  test("ignores missing/unreadable artifact messages", () => {
    expect(
      getWorkflowErrorFromJobData({ workflow_error: "Unreadable file: report.json not found" })
    ).toBeNull();
  });

  test("returns null for empty or absent errors", () => {
    expect(getWorkflowErrorFromJobData(null)).toBeNull();
    expect(getWorkflowErrorFromJobData({ workflow_error: {} })).toBeNull();
  });
});

describe("getWorkflowWarning", () => {
  test("extracts WarnException from text", () => {
    expect(getWorkflowWarning(`prefix ${WARN_EXCEPTION_MARKER}: sample threshold not met`)).toMatchObject({
      exception_type: WARN_EXCEPTION_MARKER,
      message: "sample threshold not met",
    });
  });

  test("extracts nested structured warnings", () => {
    expect(
      getWorkflowWarning({
        results: [
          {
            workflow_warning: {
              exception_type: WARN_EXCEPTION_MARKER,
              message: "model unavailable",
              workflow: "survival_analysis",
            },
          },
        ],
      })
    ).toMatchObject({
      exception_type: WARN_EXCEPTION_MARKER,
      message: "model unavailable",
      workflow: "survival_analysis",
    });
  });

  test("supports legacy status WARN objects", () => {
    expect(getWorkflowWarning({ status: "WARN", message: "legacy warning" })).toMatchObject({
      status: "WARN",
      message: "legacy warning",
    });
  });

  test("returns null when no warning exists", () => {
    expect(getWorkflowWarning({ status: "OK", message: "all good" })).toBeNull();
  });
});
