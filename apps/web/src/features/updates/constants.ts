import type { SubjectKind, UpdateFilter } from "@shared/api/generated";

export const UPDATES_PAGE_SIZE = 30;

export const UPDATE_FILTERS: readonly UpdateFilter[] = [
  "all",
  "needs_you",
  "done",
  "failed",
  "held",
];

export const UPDATE_FILTER_LABELS: Record<UpdateFilter, string> = {
  all: "All",
  needs_you: "Needs you",
  done: "Done",
  failed: "Failed",
  held: "Waiting",
};

export const SUBJECT_KIND_LABELS: Record<SubjectKind, string> = {
  ask: "Request",
  workflow_run: "Workflow",
  todo_run: "Task",
  reminder: "Reminder",
  browser_job: "Browser",
  account: "Account",
  approval: "Approval",
};
