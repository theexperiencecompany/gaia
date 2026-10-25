import * as os from "node:os";

/** A path as a person reads it: under the home directory it starts with ~. */
export function homeRelative(
  filePath: string,
  home: string = os.homedir(),
): string {
  if (filePath === home) return "~";
  return filePath.startsWith(`${home}/`)
    ? `~${filePath.slice(home.length)}`
    : filePath;
}
