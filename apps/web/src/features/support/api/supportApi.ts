import type {
  SupportRequestCreate,
  SupportRequestSubmissionResponse,
} from "@shared/api/generated";
import { api, binaryField, formDataSerializer } from "@/lib/api/typed";

export type {
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
};
