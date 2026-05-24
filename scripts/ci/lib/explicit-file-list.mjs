// Shared helper for the CI gate scripts (check-*.mjs).
//
// Returns the explicit list of files a lane is scoped to: the newline-separated
// CHANGED_FILES env var plus any non-flag argv entries. Empty when neither is
// provided, in which case the caller falls back to a full repo scan. Each
// caller applies its own extension / scope / ignore filtering to the result.
export function explicitFileList() {
  const fromEnv = (process.env.CHANGED_FILES ?? "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const fromArgv = process.argv.slice(2).filter((a) => !a.startsWith("-"));
  return [...fromEnv, ...fromArgv];
}
