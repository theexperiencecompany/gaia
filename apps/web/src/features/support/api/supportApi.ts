import type {
  PublicSupportRequestCreate,
  SupportRequestCreate,
  SupportRequestSubmissionResponse,
} from "@shared/api/generated";
import { api, binaryField, formDataSerializer } from "@/lib/api/typed";

export type {
  PublicSupportRequestCreate,
  SupportRequestCreate,
  SupportRequestSubmissionResponse,
} from "@shared/api/generated";

export const supportApi = {
  /**
   * Submit a support or feature request.
   *
   * Attachments go to the multipart route; the body is the schema's own type
   * either way, so a renamed field fails to compile instead of at runtime.
   */
  submitRequest: (
    requestData: SupportRequestCreate,
    attachments?: File[],
  ): Promise<SupportRequestSubmissionResponse> =>
    attachments && attachments.length > 0
      ? api.post("/api/v1/support/requests/with-attachments", {
          body: { ...requestData, attachments: attachments.map(binaryField) },
          bodySerializer: formDataSerializer,
          errorMessage: "Failed to submit support request",
        })
      : api.post("/api/v1/support/requests", {
          body: requestData,
          errorMessage: "Failed to submit support request",
        }),

  /**
   * Submit a contact request without a session, behind a Turnstile token.
   *
   * Silent: the caller shows the API's own message, which says whether the
   * bot check or the request itself failed.
   */
  submitPublicRequest: (
    requestData: PublicSupportRequestCreate,
  ): Promise<SupportRequestSubmissionResponse> =>
    api.post("/api/v1/support/requests/public", {
      body: requestData,
      silent: true,
    }),
};
