import React from "react";

const FooterBar: React.FC = () => {
  return (
    <div
      className="footer-bar-block-01"
    >
      <div
        className="footer-bar-block-02"
      >
        <img
          src="/logos/openfhe_logo.png"
          alt="OpenFHE logo"
          className="footer-bar-open-fhe-logo"

          onClick={() => window.open("https://openfhe.org/", "_blank")}
        />


        {/* Commenting this code out until we clear this with our lawyers: */}

        {/* <div style={{ width: "1px", height: "24px", background: "#ccc" }} />

        <img
          src="/logos/nvflare_logo.png"
          alt="NVFlare logo"
          style={{ height: "24px", width: "auto", cursor: "pointer" }}
        /> */}
      </div>

      <div
        className="footer-bar-block-03"
      >
        <img
          src="/logos/icf_logo2.png"
          alt="ICF logo"
          className="footer-bar-shared-01"
          onClick={() => window.open("https://www.icf.com/", "_blank")}
        />

        <div className="footer-bar-shared-02" />

        <img
          src="/logos/duality_logo.png"
          alt="Duality logo"
          className="footer-bar-duality-logo"
          onClick={() => window.open("https://dualitytech.com/", "_blank")}
        />

        <div className="footer-bar-shared-02" />

        <img
          src="/logos/dfci_logo.png"
          alt="DFCI logo"
          className="footer-bar-shared-01"
          onClick={() => window.open("https://www.dana-farber.org/", "_blank")}
        />
      </div>
    </div>
  );
};

export default FooterBar;