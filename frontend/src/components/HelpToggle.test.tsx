import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { HelpPanel, HelpToggle } from "./HelpToggle";

jest.mock("./AnimateIn", () => ({
  AnimateIn: ({ children }: { children: any }) => children,
}));

describe("HelpToggle", () => {
  test("invokes the toggle callback without bubbling", () => {
    const onToggle = jest.fn();
    const parentClick = jest.fn();
    render(
      <div onClick={parentClick}>
        <HelpToggle open={false} onToggle={onToggle} ariaLabel="Show help" />
      </div>
    );

    fireEvent.click(screen.getByRole("button", { name: "Show help" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(parentClick).not.toHaveBeenCalled();
  });
});

describe("HelpPanel", () => {
  test("does not render while closed", () => {
    render(<HelpPanel open={false} text="Some help" />);
    expect(screen.queryByText("Some help")).not.toBeInTheDocument();
  });

  test("does not render blank string help", () => {
    const { container } = render(<HelpPanel open text="   " />);
    expect(container).toBeEmptyDOMElement();
  });

  test("renders trimmed string content when open", () => {
    render(<HelpPanel open text="  Useful help  " />);
    expect(screen.getByText("Useful help")).toBeInTheDocument();
  });
});
