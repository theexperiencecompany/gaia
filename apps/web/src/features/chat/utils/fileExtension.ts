/** Lowercased text after a file name's last dot ("Report.PDF" -> "pdf"). */
export function getExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() || "";
}
