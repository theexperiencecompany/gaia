import { apiauth } from "@/lib/api/client";

export interface SupportRequest {
  type: "support" | "feature";
  title: string;
  description: string;
  attachments?: File[];
}

export interface SupportResponse {
  success: boolean;
  message: string;
  ticket_id?: string;
}

class SupportApiService {
  /**
   * Submit a support or feature request
   */
  async submitRequest(requestData: SupportRequest): Promise<SupportResponse> {
    try {
      // If there are attachments, use FormData
      if (requestData.attachments && requestData.attachments.length > 0) {
        const formData = new FormData();
        formData.append("type", requestData.type);
        formData.append("title", requestData.title);
        formData.append("description", requestData.description);

        // Append each attachment
        requestData.attachments.forEach((file) => {
          formData.append("attachments", file);
        });

        const response = await apiauth.post<SupportResponse>(
          "support/requests/with-attachments",
          formData,
          {
            headers: {
              "Content-Type": "multipart/form-data",
            },
          },
        );
        return response.data;
      } else {
        // No attachments, use regular JSON
        const response = await apiauth.post<SupportResponse>(
          "support/requests",
          {
            type: requestData.type,
            title: requestData.title,
            description: requestData.description,
          },
        );
        return response.data;
      }
    } catch (error) {
      console.error("Error submitting support request:", error);
      throw new Error("Failed to submit support request");
    }
  }
}

export const supportApi = new SupportApiService();
