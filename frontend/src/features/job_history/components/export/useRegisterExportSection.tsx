import { useEffect, useMemo } from "react";
import { useExportRegistry } from "./ExportContext";
import { ExportSection } from "../../utils/ExportDocTypes";

type Args = {
  id: string;
  order: number;
  title?: string;
  exportSection: () => ExportSection | null | Promise<ExportSection | null>;
};

export function useRegisterExportSection({ id, order, title, exportSection }: Args) {
  const { register } = useExportRegistry();

  const stable = useMemo(() => ({ id, order, title, exportSection }), [id, order, title, exportSection]);

  useEffect(() => {
    return register({
      id: stable.id,
      order: stable.order,
      title: stable.title,
      exportSection: stable.exportSection,
    });
  }, [register, stable]);
}
