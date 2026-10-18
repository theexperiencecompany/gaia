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

export const DOCKER_GROUP_NOTE =
  "Your user was added to the 'docker' group. Other terminals get it after you log out and back in (or run 'newgrp docker'); until then, 'gaia status' there can't reach Docker.";

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
  return outcome.startedServices === 0 ? `${state} · nothing to do` : state;
}

/** One line saying how agent code runs on this instance. */
export function codeSandboxSummary(enabled: boolean): string {
  return enabled
    ? "on, in local containers on this machine"
    : "off · turn on: gaia up --code-sandbox, or add an E2B key in Settings";
}

const NETWORK_LABEL = "On your network";

function localNameRow(outcome: UpOutcome): SummaryRow | null {
  if (outcome.localNameProblem) {
    return {
      label: NETWORK_LABEL,
      text: `gaia.local isn't set up: ${outcome.localNameProblem}`,
      tone: "warn",
    };
  }
  if (!outcome.localUrl) return null;
  return {
    label: NETWORK_LABEL,
    text: `${outcome.localUrl}, from phones and other computers here`,
    url: outcome.localUrl,
  };
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
    const setupUrl = `${outcome.webUrl}/setup`;
    rows.push(
      outcome.setupComplete
        ? {
            label: "Next",
            text: `Open ${outcome.webUrl}`,
            url: outcome.webUrl,
            tone: "primary",
          }
        : {
            label: "Next",
            text: `Open ${setupUrl} to create your admin account and pick an AI model.`,
            url: setupUrl,
            tone: "primary",
          },
    );
    const others = outcome.reachableUrls.filter(
      (url) => url !== outcome.webUrl,
    );
    if (others.length > 0) {
      rows.push({ label: "Also at", text: others.join(", "), tone: "dim" });
    }
  }
  const network = localNameRow(outcome);
  if (network) rows.push(network);
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
  rows.push({
    label: "Code execution",
    text: codeSandboxSummary(outcome.codeSandbox),
    tone: "dim",
  });
  if (outcome.joinedDockerGroup) {
    rows.push({ label: "Docker", text: DOCKER_GROUP_NOTE, tone: "warn" });
  }

  return {
    tone: outcome.noStart || outcome.stillStarting ? "pending" : "success",
    headline: headline(outcome),
    rows,
  };
}
