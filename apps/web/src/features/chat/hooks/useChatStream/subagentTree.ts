import type {
  SubagentGroupData,
  ToolDataEntry,
} from "@/config/registries/toolRegistry";

/** Recursively find and update a SubagentGroupData by ID anywhere in the tree. */
export const updateSubagentGroup = (
  group: SubagentGroupData,
  targetId: string,
  updater: (g: SubagentGroupData) => SubagentGroupData,
): SubagentGroupData => {
  if (group.subagent_id === targetId) return updater(group);
  return {
    ...group,
    nested_subagents: group.nested_subagents.map((nested) =>
      updateSubagentGroup(nested, targetId, updater),
    ),
  };
};

/** Apply updateSubagentGroup across the full tool_data list. */
export const updateSubagentInToolData = (
  toolData: ToolDataEntry[],
  targetId: string,
  updater: (g: SubagentGroupData) => SubagentGroupData,
): ToolDataEntry[] =>
  toolData.map((entry) => {
    if (entry.tool_name !== "subagent_group") return entry;
    return {
      ...entry,
      data: updateSubagentGroup(
        entry.data as SubagentGroupData,
        targetId,
        updater,
      ),
    };
  });
