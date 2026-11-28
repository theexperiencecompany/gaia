import { api, formDataSerializer } from "@/lib/api/typed";
import type { ApiBody } from "@/lib/api/typed.types";

export const mailApi = {
  // Send email
  sendEmail: (body: ApiBody<"post", "/api/v1/gmail/send">) =>
    api.post("/api/v1/gmail/send", {
      body,
      bodySerializer: formDataSerializer,
      successMessage: "Email sent successfully",
      errorMessage: "Failed to send email",
    }),

  // Send draft email
  sendDraft: (draftId: string) =>
    api.post("/api/v1/gmail/drafts/{draft_id}/send", {
      path: { draft_id: draftId },
      successMessage: "Draft sent successfully",
      errorMessage: "Failed to send draft",
    }),
};
