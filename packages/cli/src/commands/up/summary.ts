/**
 * What a finished `gaia up` tells the user, as data both the Ink card and the
 * plain (non-TTY) summary render, so the two never drift. One primary action
 * (open the setup page, or GAIA once set up), then secondary facts, then the
 * commands to come back with.
 * @module commands/up/summary
 */

import { LLM_PROVIDER_NAMES } from "../../lib/llm-flags.js";
import { LOCAL_ROOT_COPY_COMMAND } from "../../lib/local-certificate.js";
import { formatElapsed } from "../../lib/run-steps.js";
import type { SummaryRow, UpOutcome, UpSummary } from "./summary.types.js";

/** The commands listed under the card: name, then what it is for. */
export const NEXT_COMMANDS: readonly [string, string][] = [
  ["gaia status", "check health"],
  ["gaia stop", "stop GAIA"],
  ["gaia doctor", "find problems"],
  ["gaia --help", "all commands"],
];

function headline(outcome: UpOutcome): string {
  if (outcome.noStart) return "GAIA is set up · nothing was started";
  if (outcome.stillStarting) return "GAIA is still starting";
  const state =
    outcome.startedServices === 0
      ? "GAIA is already running"
      : `GAIA is running · ready in ${formatElapsed(outcome.elapsedMs)}`;
  if (outcome.unsavedProvider) {
    return `${state} · your ${LLM_PROVIDER_NAMES[outcome.unsavedProvider]} key wasn't saved`;
  }
  if (outcome.certificateProblem) {
    return "GAIA is running · its HTTPS certificate isn't ready";
  }
  return outcome.startedServices === 0 ? `${state} · nothing to do` : state;
}

/** Why gaia.local isn't set up, when this run tried and could not. */
function localNameProblemRow(outcome: UpOutcome): SummaryRow | null {
  if (!outcome.localNameProblem) return null;
  return {
    label: "gaia.local",
    text: `isn't set up: ${outcome.localNameProblem}`,
    tone: "warn",
  };
}

/**
 * The one address to open (a domain, else gaia.local, else webUrl) and the
 * others; LAN addresses only when gaia.local can't stand in for them.
 */
function addresses(outcome: UpOutcome): { primary: string; others: string[] } {
  const primary = outcome.localUrl ?? outcome.webUrl;
  const others = [
    outcome.localhostUrl,
    ...(outcome.localUrl ? [] : outcome.lanUrls),
  ].filter((url) => url !== primary);
  return { primary, others };
}

export function buildUpSummary(outcome: UpOutcome): UpSummary {
  const rows: SummaryRow[] = [];
  if (outcome.noStart) {
    rows.push({
      label: "Next",
      text: "Start it with gaia start",
      tone: "primary",
    });
  } else {
    if (outcome.stillStarting) {
      rows.push({
        label: "Status",
        text: "It is still starting in the background. Check again with gaia status.",
        tone: "warn",
      });
    }
    const { primary, others } = addresses(outcome);
    const setupUrl = `${primary}/setup`;
    rows.push(
      outcome.setupComplete
        ? {
            label: "Next",
            text: `Open ${primary}`,
            url: primary,
            tone: "primary",
          }
        : {
            label: "Next",
            text: `Open ${setupUrl} to create your admin account.`,
            url: setupUrl,
            tone: "primary",
          },
    );
    if (others.length > 0) {
      rows.push({ label: "Also at", text: others.join(", "), tone: "dim" });
    }
  }
  const localNameProblem = localNameProblemRow(outcome);
  if (localNameProblem) rows.push(localNameProblem);
  if (outcome.certificateProblem) {
    rows.push({
      label: "HTTPS",
      text: outcome.certificateProblem,
      tone: "warn",
    });
  }
  if (outcome.localCertificate) {
    rows.push({
      label: "Certificate",
      text: `from GAIA's own certificate authority, so browsers warn until a device trusts it. Copy it with: ${LOCAL_ROOT_COPY_COMMAND}`,
      tone: "warn",
    });
  }
  if (outcome.savedProvider) {
    rows.push({
      label: "AI",
      text: `${LLM_PROVIDER_NAMES[outcome.savedProvider]} key saved · change it in Settings`,
    });
  }

  return {
    tone:
      outcome.noStart || outcome.stillStarting || outcome.certificateProblem
        ? "pending"
        : "success",
    headline: headline(outcome),
    rows,
  };
}
