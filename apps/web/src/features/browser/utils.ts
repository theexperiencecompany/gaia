import type {
  BrowserHandoffSnapshot,
  BrowserResultSnapshot,
  BrowserSessionSnapshot,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "@/types/features/browserTaskTypes";
import {
  CONNECT_RUNNERS,
  type ConnectRunner,
  GAIA_CONNECT_DEFAULT_API_ORIGIN,
  GAIA_CONNECT_INSTALL_URL,
} from "./constants";
import type { BrowserCardPhase, BrowserCardStatus } from "./types";

/** Machine states → plain language the user understands at a glance: one
 * table for the chat card, the side panel and the task history. `color` is the
 * chip's; `dot`/`text` are the history row's status line. */
export const BROWSER_STATUS_META: Record<
  BrowserCardStatus,
  {
    label: string;
    color: "default" | "primary" | "success" | "danger" | "warning";
    dot: string;
    text: string;
  }
> = {
  running: {
    label: "Working",
    color: "primary",
    dot: "bg-[#00bbff]",
    text: "text-[#00bbff]",
  },
  awaiting_user: {
    label: "Action needed",
    color: "warning",
    dot: "bg-amber-500",
    text: "text-amber-400",
  },
  completed: {
    label: "Done",
    color: "success",
    dot: "bg-emerald-500",
    text: "text-emerald-400",
  },
  failed: {
    label: "Couldn't finish",
    color: "danger",
    dot: "bg-red-500",
    text: "text-red-400",
  },
  cancelled: {
    label: "Stopped",
    color: "default",
    dot: "bg-zinc-500",
    text: "text-zinc-400",
  },
};

const ENDED_STATUSES: ReadonlySet<BrowserCardStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

/** The card's status, derived once from its folded snapshots: the result's
 * when the run ended, else waiting on the user, else the session's own. */
export function browserCardPhase({
  session,
  pendingHandoff,
  result,
}: FoldedBrowserTask): BrowserCardPhase {
  const status: BrowserCardStatus =
    result?.status ??
    (pendingHandoff ? "awaiting_user" : (session?.status ?? "running"));
  return {
    status,
    ended: ENDED_STATUSES.has(status),
    working: status === "running",
  };
}

/** A browser card's state, folded from every snapshot its run sent. */
export interface FoldedBrowserTask {
  /** The card's identity: its first session, which a fallback to a new one never changes. */
  cardId?: string;
  session?: BrowserSessionSnapshot;
  steps: BrowserStepSnapshot[];
  /** The handoff waiting on the user, if one still is. */
  pendingHandoff?: BrowserHandoffSnapshot;
  result?: BrowserResultSnapshot;
}

/** Fold a card's snapshots, in the order they arrived, into what it shows. */
export function foldBrowserTask(
  snapshots: BrowserTaskSnapshot[],
): FoldedBrowserTask {
  let cardId: string | undefined;
  let session: BrowserSessionSnapshot | undefined;
  let result: BrowserResultSnapshot | undefined;
  const steps = new Map<number, BrowserStepSnapshot>();
  const handoffs = new Map<string, BrowserHandoffSnapshot>();

  for (const snap of snapshots) {
    if (snap.kind === "session") {
      session = snap;
      cardId ??= snap.session_id ?? undefined;
    } else if (snap.kind === "step") steps.set(snap.index, snap);
    else if (snap.kind === "handoff")
      handoffs.set(snap.handoff_id, snap); // last wins
    else if (snap.kind === "result") result = snap;
  }

  return {
    cardId,
    session,
    result,
    steps: [...steps.values()].sort((a, b) => a.index - b.index),
    // The run's end settles a handoff it never sent a resolved snapshot for.
    pendingHandoff: result
      ? undefined
      : [...handoffs.values()].find((h) => h.status === "pending"),
  };
}

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
