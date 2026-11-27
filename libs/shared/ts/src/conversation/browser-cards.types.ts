/** Browser-automation card payloads, carried as `browser_task_data` tool_data on a work item. */

import type {
  BrowserTaskDataCard,
  HandoffStatus,
  SensitiveCategory,
} from "../api/generated";

export type {
  BrowserAction,
  BrowserHandoffSnapshot,
  BrowserResultSnapshot,
  BrowserSessionSnapshot,
  BrowserSessionStatus,
  BrowserStepSnapshot,
} from "../api/generated";

export type BrowserHandoffStatus = HandoffStatus;

export type BrowserSensitiveCategory = SensitiveCategory;

export type BrowserTaskSnapshot = BrowserTaskDataCard["data"];
