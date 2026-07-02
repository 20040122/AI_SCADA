const PREVIEW_BASE = "http://daoscada.local/hmi-ui/";

export function toPngUrl(imagePath: string): string {
  return `${PREVIEW_BASE}${imagePath.replace(/\.json$/i, ".png")}`;
}
