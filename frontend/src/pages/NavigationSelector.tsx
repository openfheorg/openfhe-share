import React from "react";
import type { AppScreen } from "../App";
import { UserRole, useUserRole } from "../context/UserRoleContext";
import { Project } from "../types/Project";

interface NavigationSelectorProps {
  projects: Project[];
  selectedProjectId: number | null;
  selectedScreen: AppScreen;
  onSelectHome: () => void;
  onSelectProject: (project: Project) => void;
  onSelectJobHistory: (project: Project) => void;
  onSelectJobRunner: (project: Project) => void;
  onSelectProjectSettings: (project: Project) => void;
  onSelectNVFlareManager: () => void;
  onSelectUserSettings: () => void;
  projectsOpen: boolean;
  onProjectsOpenChange: (open: boolean) => void;
}

const NavigationSelector: React.FC<NavigationSelectorProps> = ({
  projects,
  selectedProjectId,
  selectedScreen,
  onSelectHome,
  onSelectProject,
  onSelectJobHistory,
  onSelectJobRunner,
  onSelectProjectSettings,
  onSelectNVFlareManager,
  onSelectUserSettings,
  projectsOpen,
  onProjectsOpenChange,
}) => {
  const role = useUserRole();
  const canRunAnalysis = role === UserRole.INITIATOR;

  const homeSelected = selectedScreen === "home" && selectedProjectId === null;

  return (
    <aside className="project-tab-rail" aria-label="SHARE navigation">
      <button
        type="button"
        className={`landing-nav-primary-option landing-nav-home-option ${homeSelected ? "selected" : ""}`}
        aria-current={homeSelected ? "page" : undefined}
        onClick={onSelectHome}
      >
        <img src="/icons/nav_icon_home.png" alt="" aria-hidden="true" />
        <span>Home</span>
      </button>

      <button
        type="button"
        className="project-tab-rail-heading project-tab-rail-heading-button"
        aria-expanded={projectsOpen}
        aria-controls="share-project-navigation-list"
        onClick={() => onProjectsOpenChange(!projectsOpen)}
      >
        <span className="project-tab-heading-label">
          <span className={`project-tab-heading-chevron ${projectsOpen ? "open" : ""}`} aria-hidden="true">▸</span>
          <img src="/icons/nav_icon_projects_list.png" alt="" aria-hidden="true" />
          <span>Projects</span>
        </span>
        <span className="project-tab-count">{projects.length}</span>
      </button>

      <div
        id="share-project-navigation-list"
        className={`project-tab-list-shell ${projectsOpen ? "open" : ""}`}
        aria-hidden={!projectsOpen}
      >
      <div className="project-tab-list" aria-label="Projects">
        {projects.map((project) => {
          const projectSelected = project.id === selectedProjectId;
          const projectContextSelected = projectSelected && !["nvflare_manager", "user_settings"].includes(selectedScreen);
          const overviewSelected = projectContextSelected && selectedScreen === "home";
          const historySelected = projectContextSelected && selectedScreen === "job_history";
          const runnerSelected = projectContextSelected && selectedScreen === "job_runner";
          const settingsSelected = projectContextSelected && selectedScreen === "project_settings";
          const projectNameNeedsNavSpacing = project.name.length > 28;
          return (
            <div
              className={`project-nav-group ${projectContextSelected ? "selected-project" : ""} ${projectNameNeedsNavSpacing ? "long-project-title" : ""}`}
              key={project.id}
            >
              <button
                id={`project-tab-${project.id}`}
                type="button"
                aria-current={overviewSelected ? "page" : undefined}
                className={`project-tab-button ${overviewSelected ? "selected" : ""}`}
                onClick={() => onSelectProject(project)}
              >
                <span className="project-tab-icon-wrap" aria-hidden="true">
                  <img src={`/icons/projects/${project.id}/icon.png`} alt="" />
                </span>
                <span className="project-tab-copy">
                  <span className="project-tab-name">{project.name}</span>
                </span>
              </button>

              <div
                className={`project-nav-submenu-shell ${projectContextSelected ? "open" : ""}`}
                aria-hidden={!projectContextSelected}
              >
                <div className="project-nav-submenu">
                  <div className="project-nav-submenu-inner" aria-label={`${project.name} navigation`}>
                    <button
                      type="button"
                      tabIndex={projectContextSelected ? 0 : -1}
                      className={`project-nav-submenu-button ${historySelected ? "selected" : ""}`}
                      aria-current={historySelected ? "page" : undefined}
                      onClick={() => onSelectJobHistory(project)}
                    >
                      View Analysis History
                    </button>

                    {canRunAnalysis ? (
                      <button
                        type="button"
                        tabIndex={projectContextSelected ? 0 : -1}
                        className={`project-nav-submenu-button ${runnerSelected ? "selected" : ""}`}
                        aria-current={runnerSelected ? "page" : undefined}
                        onClick={() => onSelectJobRunner(project)}
                      >
                        Run New Analysis
                      </button>
                    ) : null}

                    <div className="project-nav-submenu-divider" aria-hidden="true" />

                    <button
                      type="button"
                      tabIndex={projectContextSelected ? 0 : -1}
                      className={`project-nav-submenu-button ${settingsSelected ? "selected" : ""}`}
                      aria-current={settingsSelected ? "page" : undefined}
                      onClick={() => onSelectProjectSettings(project)}
                    >
                      Configuration
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      </div>

      {role === UserRole.INITIATOR ? (
        <button
          type="button"
          className={`landing-nav-primary-option ${selectedScreen === "nvflare_manager" ? "selected" : ""}`}
          aria-current={selectedScreen === "nvflare_manager" ? "page" : undefined}
          onClick={onSelectNVFlareManager}
        >
          <img src="/icons/nav_icon_nvflare_manager.png" alt="" aria-hidden="true" />
          <span>NVFlare Manager</span>
        </button>
      ) : null}

      <button
        type="button"
        className={`landing-nav-primary-option ${selectedScreen === "user_settings" ? "selected" : ""}`}
        aria-current={selectedScreen === "user_settings" ? "page" : undefined}
        onClick={onSelectUserSettings}
      >
        <img src="/icons/nav_icon_user_settings.png" alt="" aria-hidden="true" />
        <span>User Settings</span>
      </button>
    </aside>
  );
};

export default NavigationSelector;
