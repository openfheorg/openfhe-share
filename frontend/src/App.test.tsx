import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import App from "./App";

jest.mock("./components/HeaderBar", () => () => null);
jest.mock("./components/FooterBar", () => () => null);
jest.mock("./features/user_manager/UserManagerMain", () => () => null);
jest.mock("./pages/SHARELandingPage", () => {
  const ReactRuntime = require("react");

  return (props: any) => {
    const projectA = { id: 101, name: "Project A" };
    const projectB = { id: 202, name: "Project B" };

    return ReactRuntime.createElement(
      "div",
      null,
      ReactRuntime.createElement(
        "div",
        { "data-testid": "mock-location" },
        `${props.activeScreen}:${props.initialProjectId ?? "none"}`
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onOpenProject?.(projectA) },
        "Open Project A"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onOpenProject?.(projectB) },
        "Open Project B"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onOpenHome?.() },
        "Open Home"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onViewJobHistory?.(projectA) },
        "Open Project A History"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onRunAnalysis?.(projectA) },
        "Open Project A Runner"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onOpenProjectSettings?.(projectA) },
        "Open Project A Configuration"
      ),
      ReactRuntime.createElement(
        "button",
        { type: "button", onClick: () => props.onViewJobResults?.(projectA, "job-1") },
        "Open Project A Results"
      ),
      props.activeScreen === "job_results"
        ? ReactRuntime.createElement(
            "button",
            { type: "button", onClick: () => props.onLeaveResults?.() },
            "Leave Results"
          )
        : null
    );
  };
});
jest.mock("./pages/LoginPage", () => {
  const ReactRuntime = require("react");
  return ({ onLogin }: { onLogin: (session: any) => void }) =>
    ReactRuntime.createElement(
      "button",
      {
        type: "button",
        onClick: () =>
          onLogin({
            role: "INITIATOR",
            username: "tester",
            projects: [],
          }),
      },
      "Mock Login"
    );
});

describe("App", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  test("starts on the login screen", () => {
    render(<App />);

    expect(screen.getByRole("button", { name: "Mock Login" })).toBeInTheDocument();
    expect(screen.queryByTestId("mock-location")).not.toBeInTheDocument();
  });

  test("moves to Home after a successful login", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Mock Login" }));

    expect(screen.getByTestId("mock-location")).toHaveTextContent("home:none");
  });

  test("records project context even when navigating between pages that share the Home screen", () => {
    const pushStateSpy = jest.spyOn(window.history, "pushState");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Mock Login" }));
    pushStateSpy.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Open Project A" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Project B" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Home" }));

    expect(pushStateSpy).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ screen: "home", projectId: 101 }),
      "",
      expect.any(String)
    );
    expect(pushStateSpy).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ screen: "home", projectId: 202 }),
      "",
      expect.any(String)
    );
    expect(pushStateSpy.mock.calls[2][0]).toEqual(
      expect.objectContaining({ screen: "home" })
    );
    expect((pushStateSpy.mock.calls[2][0] as any).projectId).toBeUndefined();
  });

  test("restores both the previous screen and project from browser history", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Mock Login" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Project A History" }));

    expect(screen.getByTestId("mock-location")).toHaveTextContent("job_history:101");

    act(() => {
      window.dispatchEvent(
        new PopStateEvent("popstate", {
          state: { __shareApp: true, screen: "home", projectId: 101 },
        })
      );
    });

    expect(screen.getByTestId("mock-location")).toHaveTextContent("home:101");
  });

  test("collapses Analysis Runner step history before leaving for another feature", () => {
    const goSpy = jest.spyOn(window.history, "go").mockImplementation(() => undefined);
    const pushStateSpy = jest.spyOn(window.history, "pushState");

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Mock Login" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Project A Runner" }));

    window.history.replaceState(
      {
        __shareApp: true,
        screen: "job_runner",
        projectId: 101,
        jobRunnerStep: "variantTable",
        jobRunnerTrail: ["filterHistory", "patientFilters", "variantTable"],
        jobRunnerProjectId: 101,
        jobRunnerDepth: 2,
      },
      "",
      window.location.href
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Project A Configuration" }));

    expect(goSpy).toHaveBeenCalledWith(-2);
    expect(screen.getByTestId("mock-location")).toHaveTextContent("job_runner:101");

    act(() => {
      window.dispatchEvent(
        new PopStateEvent("popstate", {
          state: {
            __shareApp: true,
            screen: "job_runner",
            projectId: 101,
            jobRunnerStep: "filterHistory",
            jobRunnerTrail: ["filterHistory"],
            jobRunnerProjectId: 101,
            jobRunnerDepth: 0,
          },
        })
      );
    });

    expect(screen.getByTestId("mock-location")).toHaveTextContent("project_settings:101");
    expect(pushStateSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ screen: "project_settings", projectId: 101 }),
      "",
      expect.any(String)
    );

    act(() => {
      window.dispatchEvent(
        new PopStateEvent("popstate", {
          state: {
            __shareApp: true,
            screen: "job_runner",
            projectId: 101,
            jobRunnerStep: "filterHistory",
            jobRunnerTrail: ["filterHistory"],
            jobRunnerProjectId: 101,
            jobRunnerDepth: 0,
          },
        })
      );
    });

    expect(screen.getByTestId("mock-location")).toHaveTextContent("job_runner:101");
  });

  test("uses real browser back navigation when Results was opened from an app page", () => {
    const backSpy = jest.spyOn(window.history, "back").mockImplementation(() => undefined);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Mock Login" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Project A" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Project A Results" }));

    expect(screen.getByTestId("mock-location")).toHaveTextContent("job_results:101");

    fireEvent.click(screen.getByRole("button", { name: "Leave Results" }));

    expect(backSpy).toHaveBeenCalledTimes(1);
  });
});
