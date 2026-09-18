import type { AgentCursorTarget } from "@/features/chat/components/bubbles/bot/AgentCursor";
import type {
  BrowserSessionStatus,
  BrowserStepSnapshot,
} from "@/types/features/browserTaskTypes";
import {
  CONNECT_RUNNERS,
  type ConnectRunner,
  GAIA_CONNECT_DEFAULT_API_ORIGIN,
  GAIA_CONNECT_INSTALL_URL,
} from "./constants";

/** Machine states → plain language the user understands at a glance. Shared by
 * the chat card and the browser side panel so the two never disagree. */
export const BROWSER_STATUS_META: Record<
  BrowserSessionStatus,
  {
    label: string;
    color: "default" | "primary" | "success" | "danger" | "warning";
  }
> = {
  starting: { label: "Starting", color: "default" },
  running: { label: "Working", color: "primary" },
  paused: { label: "Action needed", color: "warning" },
  completed: { label: "Done", color: "success" },
  failed: { label: "Couldn't finish", color: "danger" },
  cancelled: { label: "Stopped", color: "default" },
};

/** The origin the local `gaia-connect` tool must talk to: the web's API base
 * without its `/api/v1` path, since the tool appends that itself. */
export function connectApiOrigin(apiBaseUrl: string): string {
  return new URL(apiBaseUrl).origin;
}

/** The `--api` override the command needs, or null when the web's API is the
 * tool's built-in default (production), so the pasted command stays short. */
export function connectApiOverride(apiBaseUrl: string): string | null {
  const origin = connectApiOrigin(apiBaseUrl);
  return origin === GAIA_CONNECT_DEFAULT_API_ORIGIN ? null : origin;
}

const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** A localhost API means a developer's own checkout: the published CLI may not
 * carry `connect` yet, and they want the source in this repo anyway. */
export function isLocalApiOrigin(apiOrigin: string): boolean {
  return LOCAL_HOSTNAMES.has(new URL(apiOrigin).hostname);
}

/** The runners worth offering for this API: `source` only when it's a
 * developer's localhost checkout, where the source is right there. */
export function connectRunnersFor(
  apiOrigin: string | null,
): readonly ConnectRunner[] {
  const local = apiOrigin !== null && isLocalApiOrigin(apiOrigin);
  return CONNECT_RUNNERS.filter((r) => r !== "source" || local);
}

export interface ConnectCommandOptions {
  token: string;
  /** From `connectApiOverride`; null means the tool's default API. */
  apiOrigin: string | null;
  runner: ConnectRunner;
}

/** The one command a user pastes to sync their browser's logins. The tool
 * detects the browser and asks which sites to sync itself; every runner
 * hands it the same flags. */
export function buildConnectCommand({
  token,
  apiOrigin,
  runner,
}: ConnectCommandOptions): string {
  const flags = ["--token", token];
  if (apiOrigin) flags.push("--api", apiOrigin);
  switch (runner) {
    case "curl":
      return `curl -fsSL ${GAIA_CONNECT_INSTALL_URL} | sh -s -- ${flags.join(" ")}`;
    case "npx":
      return `npx @heygaia/cli connect ${flags.join(" ")}`;
    case "pnpm":
      return `pnpm dlx @heygaia/cli connect ${flags.join(" ")}`;
    case "bun":
      return `bunx @heygaia/cli connect ${flags.join(" ")}`;
    case "source":
      if (apiOrigin === null) {
        throw new Error("The from-source runner needs an explicit API origin");
      }
      return `go run -C tools/gaia-connect . ${flags.join(" ")}`;
  }
}

/** "9:58" from seconds remaining, clamped at 0:00 once expired. */
export function formatCountdown(secondsLeft: number): string {
  const total = Math.max(0, Math.floor(secondsLeft));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

/** Short relative time ("Just now", "5m ago", "Yesterday", "3d ago", then a date). */
export function formatRelativeDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** The agent's current cursor target — the latest step's last on-screen action.
 *
 * The point is a viewport fraction the runner resolves per action; the kind
 * drives the overlay (a click ripples, typing shows a caret). Returns null when
 * no recent action had an on-screen target (navigation, scroll, wait). */
export function latestAgentCursor(
  steps: BrowserStepSnapshot[],
): AgentCursorTarget | null {
  for (let i = steps.length - 1; i >= 0; i--) {
    const actions = steps[i].actions ?? [];
    for (let j = actions.length - 1; j >= 0; j--) {
      const action = actions[j];
      if (!action.point) continue;
      const [x, y] = action.point;
      const kind = /input|type|fill/i.test(action.name)
        ? "type"
        : /click|select|choose|tap/i.test(action.name)
          ? "click"
          : "move";
      const verb = kind === "type" ? "Typing" : "Clicking";
      const label = action.target
        ? `${verb} \u201c${action.target}\u201d`
        : verb;
      return { x, y, kind, label, key: steps[i].index * 100 + j };
    }
  }
  return null;
}
