import React from "react";
import NVFlareClientSnapshot from "../../../components/NVFlareClientSnapshot";

interface NVFlareManagerContentProps {
  embedded?: boolean;
  showBorder?: boolean;
}

const NVFlareManagerContent: React.FC<NVFlareManagerContentProps> = ({
  embedded = false,
  showBorder = true,
}) => {
  return (
    <div>
      <NVFlareClientSnapshot
        header="Client Connections"
        embedded={embedded}
        showBorder={showBorder}
      />
    </div>
  );
};

export default NVFlareManagerContent;
