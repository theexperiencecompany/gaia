import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

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

/** The API env file `gaia up` / `gaia setup` write; a checkout without it is unconfigured. */
export function apiEnvPath(repoPath: string): string {
  return path.join(repoPath, "apps", "api", ".env");
}

/** The self-host stack's base compose file, the first `-f` of every self-host compose call. */
export const SELFHOST_COMPOSE_FILE = "docker-compose.selfhost.yml";

/** Where an install keeps the self-host compose files and their .env; packages/cli owns them, so a change releases the CLI. */
const SELFHOST_DIR = "packages/cli/selfhost";

/** Where releases before the move kept them; such an install runs from here until `gaia update` moves it. */
export const LEGACY_SELFHOST_DIR = "infra/docker";

/** The developer stack's compose folder (docker-compose.yml). */
export const DEV_DOCKER_DIR = "infra/docker";

/** The current self-host folder of an install (a fresh one gets the current layout). */
export function currentSelfhostDir(root: string): string {
  return path.join(root, SELFHOST_DIR);
}

/** The folder this install's self-host stack runs from: the current layout, else the pre-move one. */
export function selfhostDir(root: string): string {
  const current = currentSelfhostDir(root);
  if (fs.existsSync(path.join(current, SELFHOST_COMPOSE_FILE))) return current;
  const legacy = path.join(root, LEGACY_SELFHOST_DIR);
  return fs.existsSync(path.join(legacy, SELFHOST_COMPOSE_FILE))
    ? legacy
    : current;
}
