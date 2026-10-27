import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { fitDescription, fitTitle } from "@/lib/seo";

/** The integration facts a marketplace page's title and description are built from. */
export type IntegrationMetaInput = Pick<
  PublicIntegrationResponse,
  | "name"
  | "category"
  | "source"
  | "description"
  | "toolCount"
  | "tools"
  | "content"
>;

/** Categories searched as "automate <name>" (GSC: "automate instacart", "instacart automation"). */
const AUTOMATE_CATEGORIES: ReadonlySet<string> = new Set([
  "lifestyle",
  "personal",
  "finance",
  "automation",
]);

/** Categories searched as "connect <name> to <assistant>" (GSC: "connect posthog to chatgpt"). */
const CONNECT_CATEGORIES: ReadonlySet<string> = new Set([
  "business",
  "analytics",
  "crm",
  "marketing",
]);

/** Most tools a description names one by one before it states the count instead. */
const MAX_NAMED_TOOLS = 3;

type SearchIntent = "mcp" | "automate" | "connect" | "ai";

function searchIntent(integration: IntegrationMetaInput): SearchIntent {
  if (integration.source === "custom") return "mcp";
  const category = integration.category.toLowerCase();
  if (AUTOMATE_CATEGORIES.has(category)) return "automate";
  if (CONNECT_CATEGORIES.has(category)) return "connect";
  return "ai";
}

function toolCountOf(integration: IntegrationMetaInput): number {
  return integration.toolCount || integration.tools?.length || 0;
}

/** "INSTACART_CREATE_RECIPE_PAGE" and "create_recipe_page" both read as "create recipe page". */
function humanizeToolName(toolName: string): string {
  const isToolkitPrefixed =
    toolName === toolName.toUpperCase() && toolName.includes("_");
  const action = isToolkitPrefixed
    ? toolName.slice(toolName.indexOf("_") + 1)
    : toolName;
  return action.replaceAll("_", " ").toLowerCase();
}

function toolsSentence(integration: IntegrationMetaInput): string {
  const count = toolCountOf(integration);
  const tools = integration.tools ?? [];
  if (count > 1 && count <= MAX_NAMED_TOOLS && tools.length === count) {
    return `Tools: ${tools.map((tool) => humanizeToolName(tool.name)).join(", ")}.`;
  }
  if (count === 0) return "";
  return count === 1 ? "1 tool available." : `${count} tools available.`;
}

/** Title for /marketplace/[slug]: leads with the phrase people search for this kind of integration. */
export function generateIntegrationTitle(
  integration: IntegrationMetaInput,
): string {
  const { name } = integration;
  const count = toolCountOf(integration);
  const intent = searchIntent(integration);

  if (intent === "mcp") {
    const subtitle =
      count > 1
        ? `${count} Tools for Your AI Assistant`
        : "Connect It to Your AI Assistant";
    return fitTitle([
      `${name} MCP Server: ${subtitle}`,
      `${name} MCP Server for AI Assistants`,
      `${name} MCP Server`,
      `${name} MCP`,
    ]);
  }

  const subtitle =
    count > 1 ? `Run ${count} Actions from Chat` : "Ask in Plain English";
  if (intent === "automate") {
    return fitTitle([
      `Automate ${name} with AI: ${subtitle}`,
      `Automate ${name} with AI`,
      `Automate ${name}`,
    ]);
  }
  if (intent === "connect") {
    return fitTitle([
      `Connect ${name} to AI: ${subtitle}`,
      `Connect ${name} to AI`,
      `${name} AI`,
    ]);
  }
  return fitTitle([
    `${name} AI Integration: ${subtitle}`,
    `${name} AI: ${subtitle}`,
    `${name} AI Integration`,
    `${name} AI`,
  ]);
}

const DESCRIPTION_LEADS: Record<SearchIntent, (name: string) => string> = {
  mcp: (name) => `Connect the ${name} MCP server to GAIA.`,
  automate: (name) => `Automate ${name} with GAIA, your AI assistant.`,
  connect: (name) => `Connect ${name} to GAIA, your AI assistant.`,
  ai: (name) => `Use ${name} with AI in GAIA.`,
};

/** Description for /marketplace/[slug]: what the integration does, from its own use cases and tools. */
export function generateIntegrationDescription(
  integration: IntegrationMetaInput,
): string {
  const [firstUseCase = "", ...otherUseCases] =
    integration.content?.useCases ?? [];
  return fitDescription([
    DESCRIPTION_LEADS[searchIntent(integration)](integration.name),
    firstUseCase,
    toolsSentence(integration),
    ...otherUseCases,
    integration.description,
    "Add it to your GAIA from this page.",
  ]);
}
