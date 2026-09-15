import { ReactNode, useEffect, useState } from "react";

export function AnimateIn({
    children,
    delayMs = 0,
    durationMs = 220
}: {
    children: ReactNode;
    delayMs?: number;
    durationMs?: number;
}) {
    const [entered, setEntered] = useState(false);

    useEffect(() => {
        const raf = requestAnimationFrame(() => setEntered(true));
        return () => cancelAnimationFrame(raf);
    }, []);

    return (
        <div
            className="animate-in-block-01" style={{ opacity: entered ? 1 : 0, transform: entered ? "translateY(0)" : "translateY(6px)", transitionDuration: `${durationMs}ms`, transitionDelay: `${delayMs}ms` }}
        >
            {children}
        </div>
    );
}