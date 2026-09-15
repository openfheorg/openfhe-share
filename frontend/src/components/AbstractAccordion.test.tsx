import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import AbstractAccordion from "./AbstractAccordion";

jest.mock("./AnimateIn", () => ({
  AnimateIn: ({ children }: { children: any }) => children,
}));

describe("AbstractAccordion", () => {
  test("toggles in uncontrolled mode", () => {
    render(
      <AbstractAccordion title="Diagnostics" defaultOpen={false}>
        Hidden details
      </AbstractAccordion>
    );

    expect(screen.queryByText("Hidden details")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Diagnostics/i }));
    expect(screen.getByText("Hidden details")).toBeInTheDocument();
  });

  test("respects controlled open state", () => {
    const onToggle = jest.fn();
    render(
      <AbstractAccordion title="Controlled" isOpen={false} onToggle={onToggle}>
        Controlled body
      </AbstractAccordion>
    );

    fireEvent.click(screen.getByRole("button", { name: /Controlled/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Controlled body")).not.toBeInTheDocument();
  });

  test("renders header-right content independently of the body", () => {
    render(
      <AbstractAccordion title="Panel" defaultOpen={false} headerRight={<span>Refresh control</span>}>
        Panel body
      </AbstractAccordion>
    );

    expect(screen.getByText("Refresh control")).toBeInTheDocument();
    expect(screen.queryByText("Panel body")).not.toBeInTheDocument();
  });

  test("can stop click propagation", () => {
    const parentClick = jest.fn();
    render(
      <div onClick={parentClick}>
        <AbstractAccordion title="Nested" stopPropagation>
          Body
        </AbstractAccordion>
      </div>
    );

    fireEvent.click(screen.getByRole("button", { name: /Nested/i }));
    expect(parentClick).not.toHaveBeenCalled();
  });
});
