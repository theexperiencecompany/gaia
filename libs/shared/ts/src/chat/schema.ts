import { z } from "zod";
import type { TimelineToolCard, ToolDataEntry } from "../api/generated";

// Only the envelope is checked here: each tool's data is validated by its payload
// model where the server built it, and a stored card keeps the shape it was built with.
const ToolCardEnvelopeSchema = z
  .object({
    tool_name: z.string(),
    data: z.unknown(),
    timestamp: z.string().nullish(),
    tool_category: z.string().optional(),
    subagent_id: z.string().optional(),
  })
  // Per-tool variants (tool_calls_data, mcp_app, …) carry extra keys.
  .loose();

function isToolCard(value: unknown): boolean {
  return ToolCardEnvelopeSchema.safeParse(value).success;
}

/** One tool card as stored and streamed, typed per tool by the API's generated union. */
export const ToolDataEntrySchema = z.custom<ToolDataEntry>(isToolCard);

/** One card the server folded into a timeline; a grouped tool's card lists every call's data. */
export const TimelineToolCardSchema = z.custom<TimelineToolCard>(isToolCard);
