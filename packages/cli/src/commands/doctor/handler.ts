/**
 * Handler for the 'doctor' command — ordered diagnostics with remediation.
 *
 * Doctor is a diagnostic command: its output is intentionally plain text in
 * both TTY and non-TTY environments (no Ink screen) so reports can be piped,
 * redirected, or pasted verbatim into an issue. Exits 1 iff any blocker
 * check failed; setup-readiness warnings never change the exit code.
 *
 * @module commands/doctor/handler
 */

import { printHeader } from "../../ui/header/header-lines.js";
import {
  type DoctorReport,
  hasBlockingFailure,
  runDoctorChecks,
} from "./flow.js";
import type { CheckResult } from "./types.js";

/** Output tag for a check result: warnings render as [warn], not [FAIL]. */
function tagFor(result: CheckResult): string {
  if (result.state === "ok") return "[ok]";
  if (result.state === "skipped") return "[skip]";
  return result.severity === "warning" ? "[warn]" : "[FAIL]";
}

/** Terminal output for CLI commands (console trips the noConsole lint rule;
 * commands write through stdout directly). */
function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

// The widest tag ("[warn]", "[skip]", "[FAIL]") plus one space of gutter.
const TAG_COLUMN_WIDTH = 7;
const LINE_INDENT = "  ";

/** Renders one check line plus its remediation hint on failure. */
function printCheck(result: CheckResult): void {
  const tag = tagFor(result).padEnd(TAG_COLUMN_WIDTH);
  const detail = result.detail ? ` — ${result.detail}` : "";
  out(`${LINE_INDENT}${tag}${result.label}${detail}`);
  if ((result.state === "fail" || result.state === "skipped") && result.fix) {
    out(`${LINE_INDENT}${" ".repeat(TAG_COLUMN_WIDTH)}Fix: ${result.fix}`);
  }
}

export function printDoctorReport(report: DoctorReport): void {
  out("gaia doctor");
  out(`  Installation: ${report.install}`);
  for (const result of report.results) {
    printCheck(result);
  }

  const blockers = report.results.filter(
    (r) => r.severity === "blocker" && r.state === "fail",
  ).length;
  const warnings = report.results.filter(
    (r) => r.severity === "warning" && r.state === "fail",
  ).length;

  const parts: string[] = [];
  if (blockers > 0) parts.push(`${blockers} blocking`);
  if (warnings > 0) parts.push(`${warnings} warning(s)`);
  out(
    `\nSummary: ${parts.length > 0 ? parts.join(", ") : "all checks passed"}.`,
  );
}

export async function runDoctor(): Promise<void> {
  await printHeader();
  const report = await runDoctorChecks();
  printDoctorReport(report);

  if (hasBlockingFailure(report)) {
    process.exitCode = 1;
  }
}
