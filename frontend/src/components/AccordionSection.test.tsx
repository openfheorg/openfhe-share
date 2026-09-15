import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import AccordionSection from "./AccordionSection";

describe("AccordionSection", () => {
  test("renders expanded by default", () => {
    render(<AccordionSection title="Details">Accordion body</AccordionSection>);

    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Accordion body")).toBeInTheDocument();
  });

  test("can start collapsed", () => {
    render(
      <AccordionSection title="Details" defaultExpanded={false}>
        Accordion body
      </AccordionSection>
    );

    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Accordion body")).not.toBeInTheDocument();
  });

  test("toggles its body and aria-expanded state", () => {
    render(
      <AccordionSection title="Details" defaultExpanded={false}>
        Accordion body
      </AccordionSection>
    );

    const trigger = screen.getByRole("button");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Accordion body")).toBeInTheDocument();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Accordion body")).not.toBeInTheDocument();
  });
});
