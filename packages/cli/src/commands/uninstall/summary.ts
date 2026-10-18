/**
 * What a finished `gaia uninstall` tells the user, as rows both the Ink card
 * and the plain (non-TTY) output render.
 * @module commands/uninstall/summary
 */

import { homeRelative } from "../../lib/paths.js";
import type { SummaryRow } from "../up/summary.js";
import {
  CLI_REMOVE_COMMAND,
  KEPT_DATA_REMOVE_COMMAND,
  type UninstallOutcome,
} from "./flow.js";

export const UNINSTALL_HEADLINE = "GAIA is uninstalled";

export function buildUninstallRows(outcome: UninstallOutcome): SummaryRow[] {
  const rows: SummaryRow[] = [];
  if (outcome.keptData) {
    const settings = outcome.installDir
      ? ` with the settings that unlock it in ${homeRelative(outcome.installDir)}`
      : "";
    rows.push({
      label: "Your data",
      text: `kept in Docker volumes${settings}; 'gaia up' picks it back up`,
    });
    rows.push({
      label: "Delete it later",
      text: KEPT_DATA_REMOVE_COMMAND,
      tone: "dim",
    });
  } else {
    rows.push({ label: "Your data", text: "deleted" });
  }
  if (outcome.backupDir) {
    rows.push({
      label: "Backup",
      text: `in ${homeRelative(outcome.backupDir)}; 'gaia restore --from' brings it back`,
    });
  }
  rows.push({
    label: "The CLI",
    text: `remove it too with ${CLI_REMOVE_COMMAND}`,
    tone: "primary",
  });
  return rows;
}
