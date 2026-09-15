import React from "react";
import { render, screen } from "@testing-library/react";
import HeaderTitle from "./HeaderTitle";

describe("HeaderTitle", () => {
  test("renders title and description", () => {
    render(<HeaderTitle title="Analysis Results" description="Project results and diagnostics" />);

    expect(screen.getByRole("heading", { name: "Analysis Results" })).toBeInTheDocument();
    expect(screen.getByText("Project results and diagnostics")).toBeInTheDocument();
  });

  test("renders an optional decorative icon", () => {
    const { container } = render(<HeaderTitle title="Analysis Results" iconPath="/report.png" />);
    const icon = container.querySelector("img");
    expect(icon).toHaveAttribute("src", "/report.png");
    expect(icon).toHaveAttribute("alt", "");
  });

  test("does not render a divider without a description", () => {
    const { container } = render(<HeaderTitle title="Analysis Results" />);
    expect(container.querySelector("hr")).toBeNull();
  });
});
