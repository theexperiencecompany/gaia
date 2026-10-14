export function getExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() || "";
}
