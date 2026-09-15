import React, { useEffect, useMemo, useRef, useState } from "react";
import { UserSession } from "../context/UserRoleContext";

interface HeaderBarProps {
  fhirServer: string | null;
  userSession: UserSession | null;
  onUserSettingsClick?: () => void;
  onSignOutClick?: () => void;
  onLogoClick?: () => void;
}

const HeaderBar: React.FC<HeaderBarProps> = ({ fhirServer, userSession, onUserSettingsClick, onSignOutClick, onLogoClick }) => {
  const [scrolled, setScrolled] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 0);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!userMenuRef.current || userMenuRef.current.contains(event.target as Node)) {
        return;
      }
      setUserMenuOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setUserMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const handleSignOut = () => {
    setUserMenuOpen(false);

    if (onSignOutClick) {
      onSignOutClick();
      return;
    }

    window.location.assign("/");
  };

  const selectedProjectDatasourcesSource = userSession?.selected_project_datasources;
  const selectedProjectDatasources = useMemo(
    () => selectedProjectDatasourcesSource || [],
    [selectedProjectDatasourcesSource]
  );

  const datasourceDisplay = useMemo(() => {
    if (!selectedProjectDatasources.length) {
      if (!fhirServer) {
        return null;
      }

      return {
        text: fhirServer,
        href: fhirServer.toLowerCase().endsWith(".json") ? null : fhirServer,
      };
    }

    if (selectedProjectDatasources.length === 1) {
      const only = selectedProjectDatasources[0];
      return {
        text: only.source,
        href: only.source.toLowerCase().endsWith(".json") ? null : only.source,
      };
    }

    return {
      text: selectedProjectDatasources
        .map((entry) => `${entry.datasource_group_name || "DEFAULT"} (${entry.source})`)
        .join(", "),
      href: null,
    };
  }, [selectedProjectDatasources, fhirServer]);

  return (
    <div className={`header ${scrolled ? "scrolled" : ""}`}>
      <div
        className="header-panel header-bar-block-01"
      >
        <div
          className="header-bar-block-02"
        >
          <div
            onClick={() => {
              if (onLogoClick) {
                onLogoClick();
                return;
              }
              window.open("https://dualitytech.com/", "_blank");
            }}
            onKeyDown={(event) => {
              if (!onLogoClick || (event.key !== "Enter" && event.key !== " ")) {
                return;
              }
              event.preventDefault();
              onLogoClick();
            }}
            role={onLogoClick ? "button" : undefined}
            tabIndex={onLogoClick ? 0 : undefined}
            title={onLogoClick ? "Return to landing page" : "Duality Technologies"}
            className="header-bar-block-03"
          >
            <div
              className="header-bar-block-04"
            >
              <img
                src="/logos/share.png"
                alt="Share logo"
                className="header-bar-share-logo"
              />
              <div
                className="header-bar-block-05"
              >
                Secure Healthcare Data Collaboration Platform
              </div>
            </div>
          </div>
        </div>

        {(userSession || datasourceDisplay) && (
          <div
            className="header-bar-block-06"
          >
            {userSession ? (
              <div
                className="header-bar-block-07"
              >
                <div ref={userMenuRef} className="header-bar-user-menu">
                  <button
                    type="button"
                    onClick={() => setUserMenuOpen((open) => !open)}
                    aria-label="Open user menu"
                    aria-expanded={userMenuOpen}
                    title="User Menu"
                    className="header-bar-open-user-menu"
                  >
                    <span className="header-bar-block-08">
                      <span className="header-bar-block-09">User:</span>
                      <span className="header-bar-block-10">
                        {userSession.username + " (" + userSession.role + "@" + userSession.client_name + ")"}
                      </span>
                    </span>
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      aria-hidden="true"
                      className="header-bar-svg"
                    >
                      <path
                        d="M6 9l6 6 6-6"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>

                  {userMenuOpen ? (
                    <div
                      className="header-bar-block-11"
                    >
                      <button
                        type="button"
                        onClick={handleSignOut}
                        className="header-bar-block-12"
                      >
                        Sign Out
                      </button>
                    </div>
                  ) : null}
                </div>

                {onUserSettingsClick ? (
                  <button
                    type="button"
                    onClick={onUserSettingsClick}
                    aria-label="Open user settings"
                    title="User Settings"
                    className="header-bar-open-user-settings"
                  >
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      aria-hidden="true"
                    >
                      <path
                        d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      <path
                        d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.48.5.86.98 1H21a2 2 0 1 1 0 4h-.62c-.48.14-.84.52-.98 1Z"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                ) : null}
              </div>
            ) : null}

            {/* {datasourceDisplay ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  width: "100%",
                  minWidth: 0,
                }}
              >
                <img
                  src="/fhir_server.png"
                  alt="FHIR Server"
                  style={{
                    height: "30px",
                    width: "auto",
                    marginRight: "2px",
                    cursor: "pointer",
                    flexShrink: 0,
                    marginTop: "-10px",
                  }}
                  onClick={() => window.open("https://hl7.org/fhir/", "_blank")}
                />

                <span
                  style={{
                    fontSize: "16px",
                    fontWeight: "400",
                    marginRight: ".5rem",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                    color: "#E12E32"
                  }}
                >
                  Source:
                </span>

                {datasourceDisplay.href ? (
                  <a
                    target="_blank"
                    rel="noreferrer"
                    href={datasourceDisplay.href}
                    style={{
                      fontSize: "14px",
                      fontWeight: "500",
                      textAlign: "right",
                      overflowWrap: "anywhere",
                      wordBreak: "break-word",
                    }}
                  >
                    {datasourceDisplay.text}
                  </a>
                ) : (
                  <span
                    style={{
                      fontSize: "16px",
                      fontWeight: "bold",
                      textAlign: "right",
                      overflowWrap: "anywhere",
                      wordBreak: "break-word",
                    }}
                  >
                    {datasourceDisplay.text}
                  </span>
                )}
              </div>
            ) : null} */}
          </div>
        )}
      </div>
    </div>
  );
};

export default HeaderBar;
