import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import HeaderBar from "./HeaderBar";
import { UserRole, UserSession } from "../context/UserRoleContext";

const session: UserSession = {
  role: UserRole.INITIATOR,
  username: "demo-user",
  client_name: "server",
  fhir_source: null,
  projects: [],
  selected_project_datasources: [],
};

describe("HeaderBar", () => {
  test("opens and closes the user menu", () => {
    render(<HeaderBar fhirServer={null} userSession={session} onSignOutClick={jest.fn()} />);

    const userMenuButton = screen.getByRole("button", { name: "Open user menu" });
    expect(userMenuButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Sign Out" })).not.toBeInTheDocument();

    fireEvent.click(userMenuButton);
    expect(userMenuButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Sign Out" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Sign Out" })).not.toBeInTheDocument();
  });

  test("uses the supplied sign-out callback", () => {
    const onSignOutClick = jest.fn();
    render(<HeaderBar fhirServer={null} userSession={session} onSignOutClick={onSignOutClick} />);

    fireEvent.click(screen.getByRole("button", { name: "Open user menu" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign Out" }));

    expect(onSignOutClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Sign Out" })).not.toBeInTheDocument();
  });

  test("opens User Settings through its callback", () => {
    const onUserSettingsClick = jest.fn();
    render(
      <HeaderBar
        fhirServer={null}
        userSession={session}
        onUserSettingsClick={onUserSettingsClick}
        onSignOutClick={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Open user settings" }));
    expect(onUserSettingsClick).toHaveBeenCalledTimes(1);
  });

  test("uses the SHARE logo callback when provided", () => {
    const onLogoClick = jest.fn();
    render(
      <HeaderBar
        fhirServer={null}
        userSession={session}
        onLogoClick={onLogoClick}
        onSignOutClick={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Share logo/i }));
    expect(onLogoClick).toHaveBeenCalledTimes(1);
  });
});
