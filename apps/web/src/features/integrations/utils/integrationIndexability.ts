/** Community integrations need this many tools to render a non-template page. */
export const MIN_INDEXABLE_TOOL_COUNT = 3;

/**
 * Quality gate for /marketplace/[slug] indexing. A community integration
 * without tools or rich content renders only name-swapped template copy
 * ("Connect X to your AI assistant…") plus an empty tools state — a
 * doorway page. Platform integrations and content-rich pages stay indexed;
 * thin UGC stays reachable (follow) but out of the index.
 */
export function isIndexableIntegration(integration: {
  source?: string;
  toolCount?: number;
  hasRichContent?: boolean;
}): boolean {
  if (integration.source === "platform") return true;
  if (integration.hasRichContent) return true;
  return (integration.toolCount ?? 0) >= MIN_INDEXABLE_TOOL_COUNT;
}
