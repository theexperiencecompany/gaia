import type { WorkRunOutcome } from "@shared/api/generated";

/** The runs' outcomes of both lists, one per run: an entry of `incoming` replaces the same run's earlier one. */
export function mergeWorkOutcomes(
  existing: WorkRunOutcome[] | null | undefined,
  incoming: WorkRunOutcome[] | null | undefined,
): WorkRunOutcome[] {
  const byRun = new Map<string, WorkRunOutcome>();
  for (const run of [...(existing ?? []), ...(incoming ?? [])]) {
    byRun.set(run.report_id, run);
  }
  return [...byRun.values()];
}
