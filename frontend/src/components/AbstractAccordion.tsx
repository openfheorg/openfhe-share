import React, { useCallback, useMemo, useState } from "react";
import { AnimateIn } from "./AnimateIn";

export type AbstractAccordionProps = {
  title: React.ReactNode;
  titleTooltip?: string;

  isOpen?: boolean;
  defaultOpen?: boolean;
  onToggle?: () => void | Promise<void>;

  stopPropagation?: boolean;

  as?: "div" | "section";

  containerStyle?: React.CSSProperties;

  headerClassName?: string;
  headerStyle?: React.CSSProperties;
  headerRight?: React.ReactNode;
  headerRowStyle?: React.CSSProperties;

  bodyClassName?: string;
  bodyStyle?: React.CSSProperties;

  chevronOpen?: string;
  chevronClosed?: string;
  chevronStyle?: React.CSSProperties;
  chevronMarginRight?: number;

  children: React.ReactNode;
};

export default function AbstractAccordion({
  title,
  titleTooltip,

  isOpen,
  defaultOpen,
  onToggle,

  stopPropagation,

  as = "div",

  containerStyle,

  headerClassName="button-href",
  headerStyle={
        width: "100%",
        textAlign: "left",
        color: "#373737",
      },
  headerRight,
  headerRowStyle,

  bodyClassName,
  bodyStyle,

  chevronOpen = "▾",
  chevronClosed = "▸",
  chevronStyle,
  chevronMarginRight = 6,

  children
}: AbstractAccordionProps) {
  const isControlled = typeof isOpen === "boolean";
  const [internalOpen, setInternalOpen] = useState<boolean>(!!defaultOpen);

  const open = isControlled ? (isOpen as boolean) : internalOpen;

  const Wrapper = useMemo(() => as, [as]);

  const handleClick = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      if (stopPropagation) e.stopPropagation();

      if (!isControlled) {
        setInternalOpen((prev) => !prev);
      }

      if (onToggle) {
        await onToggle();
      }
    },
    [stopPropagation, isControlled, onToggle]
  );

  const headerButton = (
    <button
      className={headerClassName}
      type="button"
      onClick={handleClick}
      title={titleTooltip}
      style={headerStyle}
    >
      <span style={{ marginRight: chevronMarginRight, ...chevronStyle }}>
        {open ? chevronOpen : chevronClosed}
      </span>
      {title}
    </button>
  );

  return (

    <Wrapper style={containerStyle}>

      
        <div>
          {headerRight ? (
            <div
              style={
                headerRowStyle ?? {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  width: "100%"
                }
              }
            >
              {headerButton}
              {headerRight}
            </div>
          ) : (
            headerButton
          )}

          {open && (
            <AnimateIn delayMs={0}>
            <div className={bodyClassName} style={bodyStyle}>
              {children}
            </div>
            </AnimateIn>
          )}
        </div>
    </Wrapper>
  );
}
