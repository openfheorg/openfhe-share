
import React, { useEffect, useState } from "react";
import { AppScreen } from "../../App";
import { Project } from "../../types/Project";

type ParticipationManagerScreen =
  | "participation_manager"

interface ParticipationManagerMainProps {
  setMainScreen: (screen: AppScreen) => void;
  project: Project;
}

const ParticipationManagerMain: React.FC<ParticipationManagerMainProps> = () => {

  const [screen] = useState<ParticipationManagerScreen>("participation_manager");

  const [animate, setAnimate] = useState(true);

  useEffect(() => {
    // retrigger animation when screen changes
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);



  return (
    <>
      <div className={`function-container ${animate ? "animate-in" : ""}`}>

        {screen === "participation_manager" && (
          <div></div>
        )}

      </div>
    </>
  );
};

export default ParticipationManagerMain;
