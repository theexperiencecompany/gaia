import type {
  MemoryDataCard,
  TimelineToolCard,
  ToolDataEntry,
} from "@shared/api/generated";
import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
} from "@/types/features/calendarTypes";
import type { DeepResearchResults } from "@/types/features/searchTypes";
import type { CodeData, GoogleDocsData } from "@/types/features/toolDataTypes";

/** One memory tool call's card: an add, search, update, forget, journal or document action. */
export type MemoryData = MemoryDataCard["data"];

// ToolCallEntry / SubagentGroupData canonically live in @shared/chat (shared
// turn accumulator); re-exported here so web imports keep one source of truth.
export {
  REASONING_TOOL_NAME,
  type SubagentGroupData,
  type ToolCallEntry,
} from "@shared/chat";

/** What a renderer receives for each tool the API publishes: its timeline card's data. */
type PublishedToolDataMap = {
  [Card in TimelineToolCard as Card["tool_name"]]: Card["data"];
};

/** Cards no backend produces any more but stored history still holds; their hand types stay. */
interface UnpublishedToolDataMap {
  calendar_options: CalendarOptions[];
  calendar_delete_options: CalendarDeleteOptions[];
  calendar_edit_options: CalendarEditOptions[];
  deep_research_results: DeepResearchResults;
  code_data: CodeData;
  google_docs_data: GoogleDocsData;
}

export type ToolDataMap = PublishedToolDataMap & UnpublishedToolDataMap;
export type ToolName = keyof ToolDataMap;

/** What one tool call carries, before the timeline groups it: its tool-data entry's data. */
export type ToolPayloadMap = {
  [Entry in ToolDataEntry as Entry["tool_name"]]: Entry["data"];
} & UnpublishedToolDataMap;
