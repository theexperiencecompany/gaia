import type { ToolDataEntry } from "../api/generated";
import type { TodoProgressSnapshot } from "./types";

export type { TodoProgressSnapshot };

export type StreamToolDataEntry = ToolDataEntry;

/**
 * tool_name marking a streamed tool-call-progress entry. These render via the
 * unified tool thread (not the per-tool renderers) and carry reasoning deltas.
 */
export const TOOL_CALLS_DATA_TOOL_NAME = "tool_calls_data";
