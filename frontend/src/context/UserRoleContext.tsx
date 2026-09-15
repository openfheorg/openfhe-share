import { createContext, useContext } from "react";

export enum UserRole {
  CLIENT = "CLIENT",
  INITIATOR = "INITIATOR",
  OBSERVER = "OBSERVER",
  ADMIN = "ADMIN",
}

export interface UserProjectDatasource {
  source: string;
  datasource_group_id: number | null;
  datasource_group_name: string | null;
  is_default_group: boolean;
}

export interface UserProjectAccess {
  project_id: number;
  project_name: string;
  datasources: UserProjectDatasource[];
}

export interface UserSession {
  role: UserRole;
  username: string;
  user_id?: number | null;
  client_id?: number | null;
  client_name?: string | null;
  fhir_source: string | null;
  projects: UserProjectAccess[];
  selected_project_id?: number | null;
  selected_project_datasources?: UserProjectDatasource[];
}

export const UserRoleContext = createContext<UserSession | null>(null);

export function useUserRole(): UserRole {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.role;
}

export function useUsername(): string {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.username;
}

export function useClientName(): string | null {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.client_name ?? null;
}

export function useFHIRSource(): string | null {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.fhir_source;
}

export function useUserProjects(): UserProjectAccess[] {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.projects;
}

export function useSelectedProjectDatasources(): UserProjectDatasource[] {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session.selected_project_datasources || [];
}

export function useUserSession(): UserSession {
  const session = useContext(UserRoleContext);
  if (!session) {
    throw new Error("UserRoleContext not initialized");
  }
  return session;
}
