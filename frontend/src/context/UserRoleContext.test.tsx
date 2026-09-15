import React from "react";
import { render, screen } from "@testing-library/react";
import {
  UserRole,
  UserRoleContext,
  UserSession,
  useClientName,
  useFHIRSource,
  useSelectedProjectDatasources,
  useUserProjects,
  useUsername,
  useUserRole,
} from "./UserRoleContext";

const session: UserSession = {
  role: UserRole.CLIENT,
  username: "client-user",
  client_name: "site-1",
  fhir_source: "https://example.test/fhir",
  projects: [
    {
      project_id: 2,
      project_name: "Project Two",
      datasources: [],
    },
  ],
  selected_project_id: 2,
  selected_project_datasources: [
    {
      source: "/data/demo.json",
      datasource_group_id: 3,
      datasource_group_name: "MSKChord",
      is_default_group: true,
    },
  ],
};

function ContextProbe() {
  const selected = useSelectedProjectDatasources();
  return (
    <div>
      <span>{useUserRole()}</span>
      <span>{useUsername()}</span>
      <span>{useClientName()}</span>
      <span>{useFHIRSource()}</span>
      <span>{useUserProjects()[0].project_name}</span>
      <span>{selected[0].datasource_group_name}</span>
    </div>
  );
}

describe("UserRoleContext hooks", () => {
  test("return values from the current session", () => {
    render(
      <UserRoleContext.Provider value={session}>
        <ContextProbe />
      </UserRoleContext.Provider>
    );

    expect(screen.getByText("CLIENT")).toBeInTheDocument();
    expect(screen.getByText("client-user")).toBeInTheDocument();
    expect(screen.getByText("site-1")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/fhir")).toBeInTheDocument();
    expect(screen.getByText("Project Two")).toBeInTheDocument();
    expect(screen.getByText("MSKChord")).toBeInTheDocument();
  });

  test("throws when a required hook is used outside the provider", () => {
    const consoleError = jest.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<ContextProbe />)).toThrow("UserRoleContext not initialized");
    consoleError.mockRestore();
  });
});
