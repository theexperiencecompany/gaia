/**
 * Handler for the 'doctor' command — ordered diagnostics with remediation.
 *
 * One step runs the checks (its line names each as it lands), then the report
 * lists them: plain lines, so a piped report can be pasted into an issue;
 * colour appears only on a terminal and follows NO_COLOR. Exits 1 iff any
 * blocker check failed; warnings never change the exit code.
 *
 * @module commands/doctor/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import {
  finishStep,
  initSteps,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import type { CLIStore } from "../../ui/store.js";
import {
  type DoctorReport,
  hasBlockingFailure,
  runDoctorChecks,
} from "./flow.js";
import { DOCTOR_REPORT_KEY, doctorReportLines } from "./report.js";

async function runDoctorFlow(store: CLIStore): Promise<void> {
  initSteps(store, [
    {
      id: "check",
      label: "Checking your install",
      doneLabel: "Checked your install",
    },
  ]);
  startStep(store, "check");
  const report = await runDoctorChecks((result) =>
    updateStep(store, "check", { detail: `Checked ${result.label}` }),
  );
  finishStep(
    store,
    "check",
    report.installed ? `Checked ${report.install}` : "Checked this computer",
  );
  store.updateData(DOCTOR_REPORT_KEY, report);
  if (hasBlockingFailure(report)) process.exitCode = 1;
}

export async function runDoctor(): Promise<void> {
  await runCommandUI({
    command: "doctor",
    whenNonInteractive: "plain",
    runFlow: runDoctorFlow,
    onPlainComplete: (store) => {
      const report = store.currentState.data[DOCTOR_REPORT_KEY] as
        | DoctorReport
        | undefined;
      if (!report) return;
      process.stdout.write(`${doctorReportLines(report).join("\n")}\n`);
    },
  });
}
