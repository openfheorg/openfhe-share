import {
  formatPValueForUI,
  formatWorkflowDisplayName,
  getCombinedWorkflowMetrics,
  getWorkflowErrorFromJobData,
  renderAgentDisplayLabel,
  renderPropertyDisplayLabel,
} from "./JobsDataUtils";
import { UserRole } from "../../../context/UserRoleContext";

describe("formatPValueForUI", () => {
  test("formats values below the default threshold", () => {
    expect(formatPValueForUI(0.001)).toBe("p < 0.005, -log₁₀(p) = 3.00");
  });

  test("formats values at or above the threshold", () => {
    expect(formatPValueForUI("0.05")).toBe("p > 0.005, -log₁₀(p) = 1.30");
  });

  test("supports custom threshold and precision", () => {
    expect(formatPValueForUI(0.01, { threshold: 0.05, digits: 1 })).toBe(
      "p < 0.05, -log₁₀(p) = 2.0"
    );
  });

  test("rejects invalid p-values", () => {
    expect(formatPValueForUI(-0.1)).toBeNull();
    expect(formatPValueForUI(1.1)).toBeNull();
    expect(formatPValueForUI("not-a-number")).toBeNull();
  });
});

describe("display label helpers", () => {
  test("renders property labels for analysis results", () => {
    expect(renderPropertyDisplayLabel("MUT")).toBe("Mutations Records");
    expect(renderPropertyDisplayLabel("WT")).toBe("Wild Type Records");
    expect(renderPropertyDisplayLabel("low_score")).toBe("Low Risk");
    expect(renderPropertyDisplayLabel("high_score")).toBe("High Risk");
  });

  test("renders workflow ids as friendly display names while preserving unrelated ids", () => {
    expect(formatWorkflowDisplayName("workflow_stat_analytics__cox_lasso")).toBe("Cox Lasso");
    expect(formatWorkflowDisplayName("workflow_stat_analytics_logistic_reg")).toBe("Logistic Reg");
    expect(formatWorkflowDisplayName("workflow_stat_analytics_1", "Survival Analysis", 1)).toBe("Survival Analysis Workflow 1");
    expect(formatWorkflowDisplayName("workflow_stat_analytics__cox_lasso", "Survival Analysis", 1)).toBe("Survival Analysis Cox Lasso Workflow 1");
    expect(formatWorkflowDisplayName("workflow_stat_analytics_meta_analysis_logistic_reg", "Exceptional Response Discrimination", 2)).toBe("Exceptional Response Discrimination Logistic Reg Workflow 2");
    expect(formatWorkflowDisplayName("workflow_stat_analytics_4", "Chi Square Test", 2)).toBe("Chi Square Test Workflow 2");
    expect(formatWorkflowDisplayName("Config 1", "Mean", 1)).toBe("Mean Workflow 1");
    expect(formatWorkflowDisplayName("Config 1")).toBe("Config 1");
  });

  test("renders role-aware agent labels", () => {
    expect(renderAgentDisplayLabel("agent_results", UserRole.CLIENT)).toBe("Client");
    expect(renderAgentDisplayLabel("agent_results", UserRole.INITIATOR)).toBe("Initiator");
    expect(renderAgentDisplayLabel("aggregate_results", UserRole.INITIATOR)).toBe("Aggregated");
  });
});

describe("getWorkflowErrorFromJobData", () => {
  test("reads explicit workflow errors", () => {
    expect(getWorkflowErrorFromJobData({ workflow_error: { message: "failure" } })).toEqual({
      message: "failure",
    });
  });

  test("discovers error objects in result payloads", () => {
    expect(
      getWorkflowErrorFromJobData({
        initiator_results: { exception_type: "ValueError", message: "bad input" },
      })
    ).toMatchObject({ exception_type: "ValueError", message: "bad input" });
  });
});

describe("getCombinedWorkflowMetrics", () => {
  test("sums available workflow metrics", () => {
    const result = getCombinedWorkflowMetrics({
      survival_analysis: {
        "0": {
          server_dispatch_time_sec: 1,
          server_accept_time_sec: 2,
          server_aggregation_time_sec: 3,
          payload_in_bytes: 100,
        },
        "1": {
          server_dispatch_time_sec: 4,
          server_accept_time_sec: 5,
          server_aggregation_time_sec: 6,
          payload_in_bytes: 200,
        },
      },
    });

    expect(result).toMatchObject({
      server_dispatch_time_sec: 5,
      server_accept_time_sec: 7,
      server_aggregation_time_sec: 9,
      payload_in_bytes: 300,
    });
  });
});
