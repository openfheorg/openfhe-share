import React, { useLayoutEffect, useMemo, useRef } from "react";
import AbstractAccordion from "../../../components/AbstractAccordion";
import { JobLogEntry, NVFlareJob } from "../../../types/JobsDataTypes";

interface LogOutputSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    logs?: JobLogEntry[];
    onToggle: () => void | Promise<void>;
    logScrollRef?: React.RefObject<HTMLDivElement | null>;
}

export default function LogOutputSection({
    job,
    jobKey,
    isOpen,
    logs,
    onToggle,
    logScrollRef
}: LogOutputSectionProps) {
    const localScrollRef = useRef<HTMLDivElement | null>(null);

    const mergedScrollRef = (node: HTMLDivElement | null) => {
        localScrollRef.current = node;
        if (logScrollRef) {
            (logScrollRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
        }
    };

    const logText = useMemo(() => {
        return (logs || [])
            .map((entry) => `${entry.timestamp ? `[${entry.timestamp}] ` : ""}${entry.message}`)
            .join("\n");
    }, [logs]);

    useLayoutEffect(() => {
        if (!isOpen) return;

        const scrollToBottom = () => {
            const el = localScrollRef.current;
            if (!el) return;
            el.scrollTop = el.scrollHeight;
        };

        scrollToBottom();

        const id1 = requestAnimationFrame(() => {
            scrollToBottom();

            const id2 = requestAnimationFrame(() => {
                scrollToBottom();
            });

            setTimeout(scrollToBottom, 0);

            return () => cancelAnimationFrame(id2);
        });

        return () => cancelAnimationFrame(id1);
    }, [isOpen, logText]);

    return (
        <AbstractAccordion
            title="Log output"
            titleTooltip="Show/Hide Log Output"
            isOpen={isOpen}
            onToggle={onToggle}
            stopPropagation={true}
            containerStyle={{ padding: "5px 0" }}
            bodyStyle={{ border: "1px solid black", marginTop: "5px" }}
        >
            {(() => {
                if (!logs) return <div>Loading logs…</div>;
                if (logs.length === 0) return <div>No logs available.</div>;
                return (
                    <div
                        ref={mergedScrollRef}
                        className="log-output-section-merged-scroll"
                    >
                        {logText}
                    </div>
                );
            })()}
        </AbstractAccordion>
    );
}