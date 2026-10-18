/**
 * Handler for the 'status' command — shows service health, then exits (1 when
 * part of GAIA is down). `--watch` keeps it on screen with r to check again.
 * @module commands/status/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import { MARK } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";
import { runStatusFlow, STATUS_FACTS_KEY } from "./flow.js";
import { buildStatusReport } from "./report.js";
import type { StatusFacts } from "./report.types.js";

const ROW_LABEL_WIDTH = 8;

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function reportFor(store: CLIStore) {
  const facts = store.currentState.data[STATUS_FACTS_KEY] as
    | StatusFacts
    | undefined;
  return facts ? { facts, report: buildStatusReport(facts) } : null;
}

/** The same report as the screen, as plain text for non-TTY environments. */
function printStatusSnapshot(store: CLIStore): void {
  const built = reportFor(store);
  if (!built) return;
  const { facts, report } = built;
  const mark = report.headline.kind === "ok" ? MARK.active : MARK.fail;
  out(`${mark} ${report.headline.text}`);
  if (report.headline.url) out(`  ${report.headline.url}`);
  if (report.hint) out(`  ${report.hint}`);
  if (report.rows.length > 0) out();
  for (const row of report.rows) {
    const items = row.items
      .map((item) => `${item.ok ? MARK.ok : MARK.fail} ${item.name}`)
      .join("   ");
    const note = row.items.length === 0 ? (row.note ?? "") : "";
    out(`  ${row.label.padEnd(ROW_LABEL_WIDTH)}${items}${note}`.trimEnd());
    if (row.items.length > 0 && row.note) {
      out(`  ${" ".repeat(ROW_LABEL_WIDTH)}${row.note}`);
    }
  }
  if (facts.installed) {
    out();
    out(`  Installed at ${facts.install}`);
  }
}

export async function runStatus(
  options: { watch?: boolean } = {},
): Promise<void> {
  await runCommandUI({
    command: "status",
    whenNonInteractive: "plain",
    // A pipe cannot press r: a watch there prints one snapshot.
    autoResolve: [["exit_or_refresh", "exit"]],
    runFlow: async (store) => {
      await runStatusFlow(store, options);
      if (reportFor(store)?.report.unhealthy) process.exitCode = 1;
    },
    onPlainComplete: printStatusSnapshot,
  });
}
