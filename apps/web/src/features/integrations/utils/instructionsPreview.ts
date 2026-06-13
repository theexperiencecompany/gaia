/**
 * First meaningful line of an instructions document, stripped of leading
 * Markdown markers — used as the one-line preview in rows and lists.
 */
export const instructionsPreview = (content: string): string => {
  const firstLine = content
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  return firstLine ? firstLine.replace(/^[#>*\-\s]+/, "") : "";
};
