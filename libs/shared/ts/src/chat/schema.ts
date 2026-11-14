import { z } from "zod";
import type { ToolDataEntry } from "../api/generated";

// The satisfies-check makes the generated type the arbiter. The schema may stay
// looser than its model on purpose: a parse boundary may accept more than the
// model promises, never less.
export const ToolDataEntrySchema = z
  .object({
    tool_name: z.string(),
    data: z.unknown(),
    timestamp: z.string().nullish(),
    tool_category: z.string().optional(),
    subagent_id: z.string().optional(),
  })
  // Per-tool variants (tool_calls_data, mcp_app, …) carry extra keys.
  .loose() satisfies z.ZodType<ToolDataEntry>;
