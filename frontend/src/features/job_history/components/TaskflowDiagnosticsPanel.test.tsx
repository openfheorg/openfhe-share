import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import TaskflowDiagnosticsPanel from "./TaskflowDiagnosticsPanel";
import { TaskflowDiagnosticsResponse } from "../utils/JobsDataUtils";

jest.mock("../../../components/AnimateIn", () => ({
  AnimateIn: ({ children }: { children: any }) => children,
}));

const completeDiagnostics: TaskflowDiagnosticsResponse = {
  status: { state: "complete", progress: 100, label: "Complete" },
  summary: {
    parties: ["site-1", "site-2"],
    events: 12,
    spans: 6,
    edges: 4,
    rounds: 2,
    lamport_depth: 8,
    straggler_wait_total_sec: 1.2345,
    straggler_wait_max_sec: 0.4567,
    edges_by_id: 3,
    edges_fallback: 1,
    acyclic: true,
  },
  rounds: [
    {
      workflow: "survival_analysis",
      round: 0,
      contributions: 2,
      compute_sec: { max: 1.25, slowest_client: "site-2" },
      wait_sec: { max: 0.2 },
      fetch_sec: { max: 0.1 },
      send_sec: { max: 0.05 },
      straggler_gap_sec: 0.3,
    },
  ],
  artifacts: [{ filename: "taskflow.timeline.svg" }],
};

describe("TaskflowDiagnosticsPanel", () => {
  test("renders generation progress while taskflow diagnostics are pending", () => {
    render(
      <TaskflowDiagnosticsPanel
        nvflareJobId="job-1"
        diagnostics={{ status: { state: "running", progress: 42.4, label: "Building timeline" } }}
      />
    );

    expect(screen.getByText("Building timeline")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  test("renders unavailable state without hiding the main results", () => {
    render(
      <TaskflowDiagnosticsPanel
        nvflareJobId="job-1"
        diagnostics={{ status: { state: "unavailable", progress: 100, label: "No trace data" } }}
      />
    );

    expect(screen.getByText(/No trace data/)).toBeInTheDocument();
    expect(screen.getByText(/statistical workflow results above are unaffected/i)).toBeInTheDocument();
  });

  test("starts completed diagnostics collapsed", () => {
    render(<TaskflowDiagnosticsPanel nvflareJobId="job-1" diagnostics={completeDiagnostics} />);

    expect(screen.getByRole("button", { name: /Taskflow Diagnostics/i })).toBeInTheDocument();
    expect(screen.queryByText("Trace Events")).not.toBeInTheDocument();
  });

  test("expands summary, timeline, and round metrics", () => {
    render(<TaskflowDiagnosticsPanel nvflareJobId="job-1" diagnostics={completeDiagnostics} />);

    fireEvent.click(screen.getByRole("button", { name: /Taskflow Diagnostics/i }));

    expect(screen.getByText("Trace Events")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Taskflow Timeline")).toBeInTheDocument();
    expect(screen.getByText("Per-Round Timing")).toBeInTheDocument();
    expect(screen.getAllByText("site-2").length).toBeGreaterThan(0);
    expect(screen.getByText("Acyclic")).toBeInTheDocument();
  });

  test("returns nothing for an unexpected incomplete state", () => {
    const { container } = render(
      <TaskflowDiagnosticsPanel
        nvflareJobId="job-1"
        diagnostics={{ status: { state: "complete", progress: 100, label: "Complete" } }}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });
});
