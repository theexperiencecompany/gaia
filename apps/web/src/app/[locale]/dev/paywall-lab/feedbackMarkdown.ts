import type { ConceptId, PaywallConcept } from "./concepts";

const NO_NOTES = "_No notes._";

/** The founder's notes as markdown they can paste straight back to us. */
export function feedbackMarkdown(
  concepts: PaywallConcept[],
  notes: Partial<Record<ConceptId, string>>,
  overall: string,
): string {
  const sections = concepts.map(
    (concept, index) =>
      `## ${index + 1}. ${concept.name}\n\n**Bet:** ${concept.bet}\n\n**Notes:**\n${notes[concept.id]?.trim() || NO_NOTES}`,
  );
  return [
    `# Paywall Lab feedback (${new Date().toISOString().slice(0, 10)})`,
    `## Overall\n\n${overall.trim() || NO_NOTES}`,
    ...sections,
  ].join("\n\n");
}
