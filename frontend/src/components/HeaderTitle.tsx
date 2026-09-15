import React from "react";


interface HeaderTitleProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  iconPath?: string;
  contained?: boolean;
  transparentBackground?: boolean;
}

const HeaderTitle: React.FC<HeaderTitleProps> = ({
  title,
  description,
  iconPath,
  contained = false,
  transparentBackground = false
}) => {
  return (
    <div className="page-container">
      <div
        className={[[
          contained ? "child-container-top header-title-contained" : "",
          transparentBackground ? "header-title-transparent" : ""
        ]
          .filter(Boolean)
          .join(" ") || undefined, "header-title-block-01"].filter(Boolean).join(" ")}
        style={{ padding: transparentBackground
            ? "0.5rem 0 0.75rem"
            : contained
              ? "0.65rem 1.5rem 0.8rem"
              : "1rem 2.5rem", paddingTop: contained ? "0.65rem" : ".5rem" }}
      >
        <div className="header-title-block-02" style={{ gap: contained ? "0.75rem" : "1rem" }}>
          {iconPath ? (
            <div
              className={contained ? "header-title-icon-contained" : undefined}
              style={
                transparentBackground
                  ? {
                      width: "64px",
                      height: "64px",
                      flex: "0 0 64px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      alignSelf: "flex-start",
                      background: "transparent",
                      border: 0
                    }
                  : contained
                    ? undefined
                    : {
                        background: "white",
                        marginTop: "1rem",
                        alignContent: "center",
                        justifyContent: "center",
                        width: "130px",
                        height: "110px",
                        border: "1px solid #ccc",
                        borderRadius: "4px",
                        textAlign: "center"
                      }
              }
            >
              <img
                src={iconPath}
                alt=""
                style={
                  transparentBackground
                    ? {
                        width: "56px",
                        height: "56px",
                        objectFit: "contain",
                        display: "block",
                        flexShrink: 0
                      }
                    : contained
                      ? undefined
                      : {
                          width: "100px",
                          height: "100px",
                          objectFit: "contain",
                          flexShrink: 0
                        }
                }
              />
            </div>
          ) : null}
          <div className="header-title-block-03">
            <h2
              className="header-title-h2" style={{ marginTop: contained || transparentBackground ? 0 : undefined }}
            >
              {title}
            </h2>
            {description ? <hr /> : null}
            {description ? (
              <div className="header-title-block-04" style={{ fontSize: contained ? "13px" : "14px" }}>{description}</div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

export default HeaderTitle;