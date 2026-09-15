import { toPng } from "html-to-image";

export async function downloadElementAsPng(element: HTMLElement, filename: string): Promise<void> {
  const dataUrl = await toPng(element, {
    cacheBust: true,
    pixelRatio: 2,
    backgroundColor: "#ffffff",
  });

  const a = window.document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}
