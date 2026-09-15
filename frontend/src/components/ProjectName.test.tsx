import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProjectNameWithDescription } from "./ProjectName";
import { Project } from "../types/Project";

jest.mock("./AnimateIn", () => ({
  AnimateIn: ({ children }: { children: any }) => children,
}));

const baseProject: Project = {
  id: 1,
  name: "Demo Project",
  description: "A useful project description.",
  function_restrictions_enabled: false,
  filter_schemas: {},
  functions: [],
};

describe("ProjectNameWithDescription", () => {
  test("renders the project name and hides description initially", () => {
    render(<ProjectNameWithDescription project={baseProject} />);

    expect(screen.getByText("Demo Project")).toBeInTheDocument();
    expect(screen.queryByText("A useful project description.")).not.toBeInTheDocument();
  });

  test("shows and hides the project description", () => {
    render(<ProjectNameWithDescription project={baseProject} />);

    const infoButton = screen.getByRole("button", { name: "Info about project" });
    fireEvent.click(infoButton);
    expect(screen.getByText("A useful project description.")).toBeInTheDocument();

    fireEvent.click(infoButton);
    expect(screen.queryByText("A useful project description.")).not.toBeInTheDocument();
  });

  test("does not show an info button without a description", () => {
    render(<ProjectNameWithDescription project={{ ...baseProject, description: "" }} />);
    expect(screen.queryByRole("button", { name: "Info about project" })).not.toBeInTheDocument();
  });
});
