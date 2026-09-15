import React, { useState } from "react";
import { Project } from "../types/Project";
import { HelpPanel, HelpToggle } from "./HelpToggle";

type ProjectNameWithDescriptionProps = {
  project: Project;
};

export function ProjectNameWithDescription({
  project,
}: ProjectNameWithDescriptionProps) {
  const [open, setOpen] = useState(false);
  const desc = (project?.description ?? "").trim();

  return (
    <span>
      <span className="duality-text-black">{project?.name ?? ""}</span>

      {desc ? (
        <span
          className="project-name-block-01"
        >
          <HelpToggle
            open={open}
            onToggle={() => setOpen((prev) => !prev)}
            ariaLabel="Info about project"
            title="Info about project"
          />
        </span>
      ) : null}

      {desc ? (
        <span className="help-panel-wrap" onClick={(e) => e.stopPropagation()}>
          <HelpPanel open={open} text={desc} />
        </span>
      ) : null}
    </span>
  );
}
