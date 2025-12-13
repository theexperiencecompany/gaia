import { apiService } from "@/lib/api";
import type { PinCardProps } from "@/types/features/pinTypes";

export interface PinsResponse {
  results: PinCardProps[];
}

export const pinsApi = {
  // Fetch all pinned messages
  fetchPins: async (): Promise<PinCardProps[]> => {
    const data = await apiService.get<PinsResponse>("/messages/pinned", {
      errorMessage: "Failed to fetch pinned messages",
    });
    return data.results;
  },

  // Pin a message
  pinMessage: async (messageId: string): Promise<void> => {
    return apiService.post(`/messages/${messageId}/pin`, undefined, {
      successMessage: "Message pinned successfully",
      errorMessage: "Failed to pin message",
    });
  },

  // Unpin a message
  unpinMessage: async (messageId: string): Promise<void> => {
    return apiService.delete(`/messages/${messageId}/pin`, {
      successMessage: "Message unpinned successfully",
      errorMessage: "Failed to unpin message",
    });
  },
};
