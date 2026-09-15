import React, { useEffect, useState } from "react";
import { AppScreen } from "../../App";
import HeaderTitle from "../../components/HeaderTitle";
import { ProjectNameWithDescription } from "../../components/ProjectName";
import { Project } from "../../types/Project";
import AnalysisManager from "./pages/AnalysisManager";
import FilterManagerPage from "./pages/FilterManagerPage";

type UserManagerScreen = "filter_manager" | "analysis_manager";

interface UserManagerMainProps {
  setMainScreen: (screen: AppScreen) => void;
  project: Project;
  fhirServer?: string | null;
}

const UserManagerMain: React.FC<UserManagerMainProps> = ({ setMainScreen, project, fhirServer }) => {
  const [screen, setScreen] = useState<UserManagerScreen>("filter_manager");
  const [animate, setAnimate] = useState(true);

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);

  return (
    <>
      <HeaderTitle
        title={
          <>
            Users Manager: 
            <ProjectNameWithDescription project={project} />
          </>
        }
        description="Manage source, filter, and analysis configuration used to align analysis data requirements to a FHIR source."
        // iconPath="/icons/nav_icon_users_manager.png"
      />
      
      <div className={`function-container ${animate ? "animate-in" : ""}`}>
        
        <div
          className="user-manager-main-block-01"
        >
          <button
            className={screen === "filter_manager" ? "primary-button" : "secondary-button"}
            onClick={() => setScreen("filter_manager")}
          >
            Filter Manager
          </button>

          <button
            className={screen === "analysis_manager" ? "primary-button" : "secondary-button"}
            onClick={() => setScreen("analysis_manager")}
          >
            Analysis Manager
          </button>
        </div>

        {screen === "filter_manager" && (
          <FilterManagerPage
            project={project}
            fhirServer={fhirServer ?? null}
          />
        )}

        {screen === "analysis_manager" && (
          <AnalysisManager
            project={project}
            fhirServer={fhirServer ?? null}
          />
        )}
      </div>
    </>
  );
};

export default UserManagerMain;