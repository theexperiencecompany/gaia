import type { Card } from "../types";

/** One `support_ticket_data` item (app/agents/tools/support_tool.py). */
export interface SupportTicketData {
  type: "support" | "feature";
  title: string;
  description: string;
  user_name?: string;
  user_email?: string;
}

const DRAFT_TITLE: Record<SupportTicketData["type"], string> = {
  support: "Support ticket draft",
  feature: "Feature request draft",
};
const DESCRIPTION_CITE = "Description";

function ticketCard(ticket: SupportTicketData): Card {
  return {
    title: DRAFT_TITLE[ticket.type],
    accent: "brand",
    blocks: [
      { kind: "fields", fields: [{ label: "Title", value: ticket.title }] },
      {
        kind: "quote",
        markdown: ticket.description,
        collapsible: true,
        cite: DESCRIPTION_CITE,
      },
    ],
    actions: [],
  };
}

/** The ticket the agent drafted, one card per ticket, as the web card shows it. */
export function buildSupportTicketCards(tickets: SupportTicketData[]): Card[] {
  return tickets.map(ticketCard);
}
