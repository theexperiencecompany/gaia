import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { formatToolName } from "@/features/chat/utils/chatUtils";

// Matches LoadingIndicator's expand animation.
export const expandTransition = {
  duration: 0.2,
  ease: [0.32, 0.72, 0, 1] as const,
};

function inputPath(call: ToolCallEntry): unknown {
  const { inputs } = call;
  return inputs && typeof inputs === "object"
    ? (inputs as { path?: unknown }).path
    : undefined;
}

// A markdown read returns line-numbered text (`    12\t# Heading`), whose
// prefix stops it parsing as markdown — stripped here for display so
// SKILL.md etc. render properly; the agent still gets the numbered version.
const MARKDOWN_READ_PATH = /\.(md|markdown|mdx)$/i;
export function displayToolOutput(call: ToolCallEntry): unknown {
  const { output } = call;
  if (call.tool_name === "read" && typeof output === "string") {
    const rawPath = inputPath(call);
    // Only a string path can be a markdown filename; `String({})` would yield "[object Object]".
    if (typeof rawPath === "string" && MARKDOWN_READ_PATH.test(rawPath)) {
      return output.replace(/^ *\d+\t/gm, "");
    }
  }
  return output;
}

// A read/write/edit of any `skill.md` renders as a first-class "… a Skill" step
// with the Settings→Skills plugin icon, instead of the generic tool row.
const SKILL_FILE_PATH = /(^|\/)skill\.md$/i;
const SKILL_TOOL_LABELS: Record<string, string> = {
  read: "Reading a Skill",
  write: "Writing a Skill",
  edit: "Editing a Skill",
};
function skillToolLabel(call: ToolCallEntry): string | null {
  const label = SKILL_TOOL_LABELS[call.tool_name];
  if (!label) return null;
  const rawPath = inputPath(call);
  return typeof rawPath === "string" && SKILL_FILE_PATH.test(rawPath)
    ? label
    : null;
}

// Strips separators so two labels can be compared for redundancy ("retrieve_tools" vs "Retrieve tools").
function normalizeLabel(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function categoryLabel(category: string | undefined): string {
  if (!category || category === "unknown") return "";
  return category
    .replaceAll("_", " ")
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

export interface ToolCallDisplay {
  skillLabel: string | null;
  primaryLabel: string;
  secondaryLabel: string;
  hasCategoryText: boolean;
  hasInputs: boolean;
  hasOutput: boolean;
  hasDetails: boolean;
}

export function deriveToolCallDisplay(
  call: ToolCallEntry,
  getIntegrationName: (c: ToolCallEntry) => string | undefined,
): ToolCallDisplay {
  // The skill label wins over any backend-provided custom message.
  const skillLabel = skillToolLabel(call);
  const primaryLabel =
    skillLabel || call.message || formatToolName(call.tool_name);
  const integrationLabel =
    getIntegrationName(call) || categoryLabel(call.tool_category);
  // `show_category === false` means the backend sent a curated primary label,
  // so the secondary shows the raw tool name for transparency.
  const secondaryLabel =
    call.show_category === false
      ? call.tool_name.toLowerCase()
      : integrationLabel;
  // Hide the secondary when it adds nothing, e.g. "retrieve_tools" under "Retrieve tools".
  const normPrimary = normalizeLabel(primaryLabel);
  const normSecondary = normalizeLabel(secondaryLabel);
  const hasCategoryText =
    secondaryLabel.length > 0 &&
    normSecondary.length > 0 &&
    !normPrimary.includes(normSecondary) &&
    !normSecondary.includes(normPrimary);
  const hasInputs =
    !!call.inputs &&
    typeof call.inputs === "object" &&
    Object.keys(call.inputs).length > 0;
  const hasOutput = !!call.output && call.output.trim().length > 0;
  return {
    skillLabel,
    primaryLabel,
    secondaryLabel,
    hasCategoryText,
    hasInputs,
    hasOutput,
    hasDetails: hasInputs || hasOutput,
  };
}
