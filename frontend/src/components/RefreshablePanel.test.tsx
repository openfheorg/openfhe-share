import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import RefreshablePanel from "./RefreshablePanel";

jest.mock("./AnimateIn", () => ({
  AnimateIn: ({ children }: { children: any }) => children,
}));

describe("RefreshablePanel", () => {
  test("renders a refresh action and invokes it", () => {
    const onRefresh = jest.fn();
    render(
      <RefreshablePanel header="Participation Status" onRefresh={onRefresh}>
        Current status
      </RefreshablePanel>
    );

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Current status")).toBeInTheDocument();
  });

  test("disables refresh and shows loading status while loading", () => {
    render(
      <RefreshablePanel header="Participation Status" loading onRefresh={jest.fn()} loadingStatus="Refreshing...">
        Current status
      </RefreshablePanel>
    );

    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
    expect(screen.getByText("Refreshing...")).toBeInTheDocument();
    expect(screen.queryByText("Current status")).not.toBeInTheDocument();
  });

  test("supports a collapsed accordion while keeping refresh available", () => {
    render(
      <RefreshablePanel
        header="Participation Status"
        accordion
        accordionDefaultExpanded={false}
        onRefresh={jest.fn()}
      >
        Current status
      </RefreshablePanel>
    );

    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByText("Current status")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Participation Status/i }));
    expect(screen.getByText("Current status")).toBeInTheDocument();
  });
});
