// Shared helper for the checks.mjs file-walking gates.
//
// Returns the explicit list of files a lane is scoped to: the newline-separated
// CHANGED_FILES env var plus any non-flag entries in `args`. Empty when neither
// is provided, in which case the caller falls back to a full repo scan. Each
// caller applies its own extension / scope / ignore filtering to the result.
//
// `args` is passed in rather than read off process.argv here on purpose: the
// caller is a subcommand of checks.mjs, so process.argv[2] is the subcommand
// NAME. Reading argv directly made that name look like an explicit file, which
// sent every full scan down the explicit-list path with a list that filtered to
// nothing — a gate reporting "all files within limits" having scanned none.
export function explicitFileList(args = []) {
  const fromEnv = (process.env.CHANGED_FILES ?? "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const fromArgs = args.filter((a) => !a.startsWith("-"));
  return [...fromEnv, ...fromArgs];
}
