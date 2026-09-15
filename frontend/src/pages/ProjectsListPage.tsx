import React from "react";
import ProjectListComponent from "../components/ProjectListComponent";
import { Project } from "../types/Project";

interface ProjectListPageProps {
  onProjectSelected: (project: Project) => void;
  onRunAnalysis?: (project: Project) => void;
  onViewJobHistory?: (project: Project) => void;
  onViewJobResults?: (project: Project, nvflareJobId: string) => void;
}

const ProjectListPage: React.FC<ProjectListPageProps> = ({
  onProjectSelected,
  onRunAnalysis,
  onViewJobHistory,
  onViewJobResults,
}) => {
  return (
    <div className="projects-home-page">
      <ProjectListComponent
        onProjectSelected={onProjectSelected}
        onRunAnalysis={onRunAnalysis}
        onViewJobHistory={onViewJobHistory}
        onViewJobResults={onViewJobResults}
      />
    </div>
  );
};

export default ProjectListPage;
