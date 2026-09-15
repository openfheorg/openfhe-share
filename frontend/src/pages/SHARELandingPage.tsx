import React from "react";
import type { AppScreen } from "../App";
import ProjectListComponent from "../components/ProjectListComponent";
import { Project } from "../types/Project";

interface SHARELandingPageProps {
  activeScreen: AppScreen;
  jobHistoryReloadKey?: number;
  userSettingsReloadKey?: number;
  initialProjectId?: number | null;
  resultsJobId?: string | null;
  projectsNavOpen: boolean;
  onProjectsNavOpenChange: (open: boolean) => void;
  onOpenHome?: () => void;
  onOpenProject?: (project: Project) => void;
  onRunAnalysis?: (project: Project) => void;
  onViewJobHistory?: (project: Project) => void;
  onOpenProjectSettings?: (project: Project) => void;
  onViewJobResults?: (project: Project, nvflareJobId: string) => void;
  onResultsContextLoaded?: (project: Project) => void;
  onLeaveResults?: () => void;
  onOpenNVFlareManager?: () => void;
  onOpenUserSettings?: () => void;
}

const SHARELandingPage: React.FC<SHARELandingPageProps> = ({
  activeScreen,
  jobHistoryReloadKey = 0,
  userSettingsReloadKey = 0,
  initialProjectId,
  resultsJobId,
  projectsNavOpen,
  onProjectsNavOpenChange,
  onOpenHome,
  onOpenProject,
  onRunAnalysis,
  onViewJobHistory,
  onOpenProjectSettings,
  onViewJobResults,
  onResultsContextLoaded,
  onLeaveResults,
  onOpenNVFlareManager,
  onOpenUserSettings,
}) => {
  return (
    <div className="projects-home-page">
      <ProjectListComponent
        activeScreen={activeScreen}
        jobHistoryReloadKey={jobHistoryReloadKey}
        userSettingsReloadKey={userSettingsReloadKey}
        initialProjectId={initialProjectId}
        resultsJobId={resultsJobId}
        projectsNavOpen={projectsNavOpen}
        onProjectsNavOpenChange={onProjectsNavOpenChange}
        onOpenHome={onOpenHome}
        onOpenProject={onOpenProject}
        onRunAnalysis={onRunAnalysis}
        onViewJobHistory={onViewJobHistory}
        onOpenProjectSettings={onOpenProjectSettings}
        onViewJobResults={onViewJobResults}
        onResultsContextLoaded={onResultsContextLoaded}
        onLeaveResults={onLeaveResults}
        onOpenNVFlareManager={onOpenNVFlareManager}
        onOpenUserSettings={onOpenUserSettings}
      />
    </div>
  );
};

export default SHARELandingPage;
