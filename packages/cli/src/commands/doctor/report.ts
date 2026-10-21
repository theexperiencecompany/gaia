/**
 * The doctor report as lines: a row per check, the skipped causes, then the
 * tally. The Ink screen and a piped run print the same lines.
 * @module commands/doctor/report
 */

import chalk from "chalk";
import { wrapForTerminal } from "../../lib/terminal-text.js";
import { MARK, type MarkKind } from "../../ui/constants.js";
import type { DoctorReport } from "./flow.js";
import type { CheckResult } from "./types.js";

/** Store key holding the finished report. */
export const DOCTOR_REPORT_KEY = "doctorReport";

const LABEL_WIDTH = 16;
const INDENT = "  ";

const MARK_PAINT: Record<MarkKind, (text: string) => string> = {
  ok: chalk.green,
  fail: chalk.red,
  warn: chalk.yellow,
  skip: chalk.gray,
  pending: chalk.gray,
  active: chalk.cyan,
  cancelled: chalk.yellow,
};

function markFor(result: CheckResult): MarkKind {
  if (result.state === "ok") return "ok";
  if (result.state === "skipped") return "skip";
  return result.severity === "warning" ? "warn" : "fail";
}

/** Where a row's detail and fix start: indent, mark and space, then the label column. */
const TEXT_COLUMN = INDENT.length + 2 + LABEL_WIDTH;

function checkLines(
  result: CheckResult,
  next: CheckResult | undefined,
): string[] {
  const kind = markFor(result);
  const detail = result.detail
    ? chalk.gray(wrapForTerminal(result.detail, TEXT_COLUMN))
    : "";
  const lines = [
    `${INDENT}${MARK_PAINT[kind](MARK[kind])} ${result.label.padEnd(LABEL_WIDTH)}${detail}`,
  ];
  // Rows that share a root cause share its fix: say it once, under the last of them.
  if (result.state === "fail" && result.fix && next?.fix !== result.fix) {
    lines.push(
      `${" ".repeat(TEXT_COLUMN)}${wrapForTerminal(result.fix, TEXT_COLUMN)}`,
    );
  }
  return lines;
}

/**
 * Skipped checks share a root cause already reported above (no Docker, no
 * install, no API): one line per cause, not one per check.
 */
function skippedLines(skipped: CheckResult[]): string[] {
  const byReason = new Map<string, string[]>();
  for (const result of skipped) {
    const reason = result.detail ?? "skipped";
    byReason.set(reason, [...(byReason.get(reason) ?? []), result.label]);
  }
  return [...byReason].map(
    ([reason, labels]) =>
      `${INDENT}${chalk.gray(MARK.skip)} ${chalk.gray(`Not checked: ${labels.join(", ")} (${reason})`)}`,
  );
}

function summaryLine(report: DoctorReport): string {
  const problems = report.results.filter(
    (r) => r.severity === "blocker" && r.state === "fail",
  ).length;
  const warnings = report.results.filter(
    (r) => r.severity === "warning" && r.state === "fail",
  ).length;
  if (problems === 0 && warnings === 0) {
    return chalk.green(`${MARK.ok} Everything checked out`);
  }
  const parts: string[] = [];
  if (problems > 0) {
    parts.push(chalk.red(`${problems} problem${problems === 1 ? "" : "s"}`));
  }
  if (warnings > 0) {
    parts.push(chalk.yellow(`${warnings} warning${warnings === 1 ? "" : "s"}`));
  }
  return parts.join(" · ");
}

/** The report under the step that names the install: a row per check, the skipped causes, then the tally. */
export function doctorReportLines(report: DoctorReport): string[] {
  const shown = report.results.filter((r) => r.state !== "skipped");
  return [
    ...shown.flatMap((result, i) => checkLines(result, shown[i + 1])),
    ...skippedLines(report.results.filter((r) => r.state === "skipped")),
    "",
    `${INDENT}${summaryLine(report)}`,
  ];
}
