/** Severity of a doctor check failure — blockers fail the command, warnings don't. */
export type CheckSeverity = "blocker" | "warning";

/** Lifecycle state of a single doctor check. */
export type CheckState = "ok" | "fail" | "skipped";

/** Result of one doctor check: label, state, optional detail and remediation. */
export interface CheckResult {
  id?: string;
  label: string;
  state: CheckState;
  severity: CheckSeverity;
  detail?: string;
  fix?: string;
}
