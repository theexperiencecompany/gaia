import type { SupportRequestCreate } from "@shared/api/generated";

/** A support_ticket_data draft: the create request support_tool.py prepares, plus who files it. */
export type SupportTicketData = SupportRequestCreate & {
  user_name?: string;
  user_email?: string;
};
