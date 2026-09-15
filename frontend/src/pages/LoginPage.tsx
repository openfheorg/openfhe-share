/**
 * LoginPage.tsx
 *
 * Supports normal prototype login, username-prefilled SHARE exploration links,
 * and automatic login for direct job-results links.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../constants/Constants";
import { UserRole, UserSession } from "../context/UserRoleContext";

type SessionBase = Omit<
  UserSession,
  "fhir_source" | "selected_project_id" | "selected_project_datasources"
>;

interface LoginPageProps {
  initialUsername?: string | null;
  autoLogin?: boolean;
  launchError?: string | null;
  onLogin: (session: SessionBase) => void;
}

const LoginPage: React.FC<LoginPageProps> = ({
  initialUsername,
  autoLogin = false,
  launchError,
  onLogin,
}) => {
  const [username, setUsername] = useState(initialUsername?.trim() || "");
  const [password, setPassword] = useState(""); // unused for now
  const [error, setError] = useState(launchError || "");
  const [automaticLoginPending, setAutomaticLoginPending] = useState(
    Boolean(autoLogin && initialUsername?.trim())
  );
  const automaticLoginStarted = useRef(false);

  const loginWithUsername = useCallback(
    async (requestedUsername: string) => {
      const trimmedUsername = requestedUsername.trim();

      if (!trimmedUsername) {
        throw new Error("Username was not provided");
      }

      const response = await fetch(`${API_BASE}/user/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: trimmedUsername }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Login failed");
      }

      const data = await response.json();

      if (!data.role) {
        throw new Error("Role not found for user");
      }

      onLogin({
        role: data.role as UserRole,
        username: data.username || trimmedUsername,
        user_id: data.user_id ?? null,
        client_id: data.client_id ?? null,
        client_name: typeof data.client_name === "string" ? data.client_name : null,
        projects: Array.isArray(data.projects) ? data.projects : [],
      });
    },
    [onLogin]
  );

  useEffect(() => {
    const normalizedUsername = initialUsername?.trim() || "";
    if (normalizedUsername) {
      setUsername(normalizedUsername);
    }
  }, [initialUsername]);

  useEffect(() => {
    if (!autoLogin || !initialUsername?.trim() || automaticLoginStarted.current) {
      return;
    }

    automaticLoginStarted.current = true;
    setAutomaticLoginPending(true);
    setError("");

    const runAutomaticLogin = async () => {
      try {
        await loginWithUsername(initialUsername);
      } catch (caughtError) {
        setError(
          caughtError instanceof Error
            ? caughtError.message
            : "Launch-link login failed"
        );
        setAutomaticLoginPending(false);
      }
    };

    void runAutomaticLogin();
  }, [autoLogin, initialUsername, loginWithUsername]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");

    try {
      await loginWithUsername(username);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Network error");
    }
  };

  if (automaticLoginPending) {
    return (
      <div
        className="login-page-shared-01"
      >
        <div className="login-container" aria-live="polite">
          <div className="login-page-block-01">
            <img
              src="/icons/nav_icon_users_login.png"
              alt=""
              className="login-page-shared-02"
            />
            <div>
              <h2 className="duality-mb-0p5rem">Signing In</h2>
              <div>Signing in from the SHARE Client launch link…</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="login-page-shared-01"
    >
      <form onSubmit={handleSubmit} className="login-container">
        <div className="login-page-block-02">
          <img
            src="/icons/nav_icon_users_login.png"
            alt=""
            className="login-page-shared-02"
          />
          <h2>System Login</h2>
        </div>

        {error && (
          <div role="alert" className="duality-text-red-mb-1rem">
            {error}
          </div>
        )}

        <div className="duality-mb-1">
          <label htmlFor="share-login-username">Username:</label>
          <input
            id="share-login-username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoFocus={!username}
            autoComplete="username"
            className="duality-w-100pct-p-0p5rem"
          />
        </div>

        <div className="duality-mb-1">
          <label htmlFor="share-login-password">Password:</label>
          <input
            id="share-login-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            className="duality-w-100pct-p-0p5rem"
          />
        </div>

        <div className="login-page-block-03">
          <button disabled={username.trim().length === 0} type="submit">
            Login
          </button>
        </div>

        <br />
        NOTE: User roles are in development. Use 'client_site1' or 'client_site2'
        for CLIENT accounts, and 'initiator' for the site3 INITIATOR account. No
        password needed.
      </form>
    </div>
  );
};

export default LoginPage;
