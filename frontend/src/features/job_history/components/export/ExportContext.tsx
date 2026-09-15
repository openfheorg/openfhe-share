import React, { createContext, useCallback, useContext, useRef } from "react";
import { ExportSection } from "../../utils/ExportDocTypes";

export type ExportSectionRegistration = {
  id: string;
  order: number;
  title?: string;
  exportSection: () => ExportSection | null | Promise<ExportSection | null>;
};

type ExportRegistry = {
  register: (section: ExportSectionRegistration) => () => void;
  getSections: () => ExportSectionRegistration[];
};

const ExportContext = createContext<ExportRegistry | null>(null);

export const ExportProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const sectionsRef = useRef<Map<string, ExportSectionRegistration>>(new Map());

  const register = useCallback((section: ExportSectionRegistration) => {
    sectionsRef.current.set(section.id, section);
    return () => {
      sectionsRef.current.delete(section.id);
    };
  }, []);

  const getSections = useCallback(() => {
    return Array.from(sectionsRef.current.values()).sort((a, b) => a.order - b.order);
  }, []);

  return <ExportContext.Provider value={{ register, getSections }}>{children}</ExportContext.Provider>;
};

export function useExportRegistry(): ExportRegistry {
  const ctx = useContext(ExportContext);
  if (!ctx) {
    throw new Error("useExportRegistry must be used within ExportProvider");
  }
  return ctx;
}
