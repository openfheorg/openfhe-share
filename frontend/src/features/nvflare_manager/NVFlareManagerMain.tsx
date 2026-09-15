import React, { useEffect, useState } from "react";
import { AppScreen } from "../../App";
import HeaderTitle from "../../components/HeaderTitle";
import { description_nvflare_manager } from "../../constants/Constants";
import NVFlareManagerContent from "./components/NVFlareManagerContent";
import { Project } from "../../types/Project";

type NVFlareManagerScreen = "nvflare_manager";

interface NVFlareManagerMainProps {
  setMainScreen: (screen: AppScreen) => void;
  project: Project;
}


const NVFlareManagerMain: React.FC<NVFlareManagerMainProps> = ({
  setMainScreen
}) => {
  const [screen] = useState<NVFlareManagerScreen>("nvflare_manager");
  const [animate, setAnimate] = useState(true);

  // function processAndSetScreen(screenName: NVFlareManagerScreen) {
  //   setScreen(screenName);
  // }

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);

  return (
    <>
      <HeaderTitle title={"NVFlare Manager"} 
      description={description_nvflare_manager} 
      // iconPath="/icons/nav_icon_nvflare_manager.png"
      />
      <div className={`function-container ${animate ? "animate-in" : ""}`}>
        {screen === "nvflare_manager" && (
          <div>
            <NVFlareManagerContent />
          </div>
        )}
      </div>

      <div className="page-container">
        <div className="footer-button-container">
          <button className="secondary-button" onClick={() => setMainScreen("home")}>
            Back to Home
          </button>
        </div>
      </div>
    </>
  );
};

export default NVFlareManagerMain;
