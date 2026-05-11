// Support ticket types for frontend

export type SupportTicketType = "support" | "feature";

export interface SupportTicketData {
  type: SupportTicketType;
  title: string;
  description: string;
  user_name?: string;
  user_email?: string;
}
