/**
 * Handler for the 'doctor' command — ordered diagnostics with remediation.
 *
 * Doctor is a diagnostic command: its output is plain lines (no Ink screen)
 * so a report can be piped or pasted into an issue; colour appears only on a
 * terminal and follows NO_COLOR. Exits 1 iff any blocker check failed;
 * warnings never change the exit code.
 *
 * @module commands/doctor/handler
 */

import chalk, { Chalk, type ChalkInstance } from "chalk";
import { MARK, type MarkKind } from "../../ui/constants.js";
import { printHeader } from "../../ui/header/header-lines.js";
import {
  type DoctorReport,
  hasBlockingFailure,
  runDoctorChecks,
} from "./flow.js";
import type { CheckResult } from "./types.js";

/** Terminal output for CLI commands (console trips the noConsole lint rule). */
function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

const LABEL_WIDTH = 16;
const INDENT = "  ";

/** chalk honours FORCE_COLOR and TTY detection, but not NO_COLOR. */
const paint: ChalkInstance =
  process.env.NO_COLOR !== undefined ? new Chalk({ level: 0 }) : chalk;

const MARK_PAINT: Record<MarkKind, (text: string) => string> = {
  ok: paint.green,
  fail: paint.red,
  warn: paint.yellow,
  skip: paint.gray,
  pending: paint.gray,
  active: paint.cyan,
  cancelled: paint.yellow,
};

function markFor(result: CheckResult): MarkKind {
  if (result.state === "ok") return "ok";
  if (result.state === "skipped") return "skip";
  return result.severity === "warning" ? "warn" : "fail";
}

function printCheck(result: CheckResult, next: CheckResult | undefined): void {
  const kind = markFor(result);
  const detail = result.detail ? paint.gray(result.detail) : "";
  out(
    `${INDENT}${MARK_PAINT[kind](MARK[kind])} ${result.label.padEnd(LABEL_WIDTH)}${detail}`,
  );
  // Rows that share a root cause share its fix: say it once, under the last of them.
  if (result.state === "fail" && result.fix && next?.fix !== result.fix) {
    out(`${INDENT}  ${" ".repeat(LABEL_WIDTH)}${result.fix}`);
  }
}

/**
 * Skipped checks share a root cause already reported above (no Docker, no
 * install, no API): one line per cause, not one per check.
 */
function printSkipped(skipped: CheckResult[]): void {
  const byReason = new Map<string, string[]>();
  for (const result of skipped) {
    const reason = result.detail ?? "skipped";
    byReason.set(reason, [...(byReason.get(reason) ?? []), result.label]);
  }
  for (const [reason, labels] of byReason) {
    out(
      `${INDENT}${paint.gray(MARK.skip)} ${paint.gray(`Not checked: ${labels.join(", ")} (${reason})`)}`,
    );
  }
}

function summaryLine(report: DoctorReport): string {
  const problems = report.results.filter(
    (r) => r.severity === "blocker" && r.state === "fail",
  ).length;
  const warnings = report.results.filter(
    (r) => r.severity === "warning" && r.state === "fail",
  ).length;
  if (problems === 0 && warnings === 0) {
    return paint.green(`${MARK.ok} Everything checked out`);
  }
  const parts: string[] = [];
  if (problems > 0) {
    parts.push(paint.red(`${problems} problem${problems === 1 ? "" : "s"}`));
  }
  if (warnings > 0) {
    parts.push(paint.yellow(`${warnings} warning${warnings === 1 ? "" : "s"}`));
  }
  return parts.join(" · ");
}

export function printDoctorReport(report: DoctorReport): void {
  out();
  out(`${paint.bold("gaia doctor")} ${paint.gray(report.install)}`);
  out();
  const shown = report.results.filter((r) => r.state !== "skipped");
  shown.forEach((result, i) => {
    printCheck(result, shown[i + 1]);
  });
  printSkipped(report.results.filter((r) => r.state === "skipped"));
  out();
  out(summaryLine(report));
}

export async function runDoctor(): Promise<void> {
  await printHeader();
  const report = await runDoctorChecks();
  printDoctorReport(report);

  if (hasBlockingFailure(report)) {
    process.exitCode = 1;
  }
}
