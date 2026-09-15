import React from "react";

interface CompactBannerProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  stickToBottom?: boolean;
}

const CompactBanner: React.FC<CompactBannerProps> = ({
  children,
  className,
  style,
  stickToBottom = false
}) => {
  return (
    <div
      className={[className, "compact-banner-block-01"].filter(Boolean).join(" ")}
      style={{ marginTop: stickToBottom ? "auto" : "0.5rem", ...style }}
    >
      {children}
    </div>
  );
};

export default CompactBanner;
