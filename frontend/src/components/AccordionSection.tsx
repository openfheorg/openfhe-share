import React, { useState } from "react";

type AccordionSectionProps = {
    title: React.ReactNode;
    children: React.ReactNode;
    defaultExpanded?: boolean;
    className?: string;
};

const AccordionSection: React.FC<AccordionSectionProps> = ({
    title,
    children,
    defaultExpanded = true,
    className,
}) => {
    const [expanded, setExpanded] = useState(defaultExpanded);

    return (
        <div className={className}>
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="accordion-section-block-01"
            >
                <div className="accordion-section-block-02">
                    <span
                        aria-hidden="true"
                        className="accordion-section-block-03" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
                    >
                        ▶
                    </span>
                    <h3 className="accordion-section-h3">
                        {title}
                    </h3>
                </div>

            </button>

            {expanded && <div className="duality-mt-0p75rem">{children}</div>}
        </div>
    );
};

export default AccordionSection;
