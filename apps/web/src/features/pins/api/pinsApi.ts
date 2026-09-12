import { api } from "@/lib/api/typed";

export const pinsApi = {
  // Fetch all pinned messages
  fetchPins: async () => {
    const data = await api.get("/api/v1/messages/pinned", {
      errorMessage: "Failed to fetch pinned messages",
    });
    return data.results;
  },
};
