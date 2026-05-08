/**
 * Workflow timing constants. Centralised so polling/timeouts/transient toasts
 * have a single source of truth and can be tuned without grepping the tree.
 */

export const WORKFLOW_POLLING_INTERVAL_MS = 2_000;
export const WORKFLOW_POLLING_MAX_MS = 5 * 60 * 1_000; // 5 minutes
export const WORKFLOW_TOAST_TIMEOUT_MS = 3_000;
export const WORKFLOW_REGENERATE_AUTO_CLOSE_MS = 1_500;

export const WORKFLOW_COMMUNITY_PAGE_SIZE = 12;
export const WORKFLOW_EXECUTIONS_PAGE_SIZE = 10;
