import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/client";
import { api as typedApi } from "@/lib/api/typed";

export type HoloCardData = Schema<"PersonalizationResponse">;

export type PublicHoloCardData = Schema<"PublicHoloCardResponse">;

export const holoCardApi = {
  // Get current user's holo card data (authenticated) - includes workflows
  getMyHoloCard: async () => {
    return typedApi.get("/api/v1/onboarding/personalization", { silent: true });
  },

  // Get public holo card data by card ID (no auth required) - no workflows
  getPublicHoloCard: async (cardId: string): Promise<PublicHoloCardData> => {
    const response = await api.get<PublicHoloCardData>(
      `/user/holo-card/${cardId}`,
    );
    return response.data;
  },

  // Update holo card colors (authenticated)
  updateHoloCardColors: async (
    overlayColor: string,
    overlayOpacity: number,
  ) => {
    const body = new URLSearchParams({
      overlay_color: overlayColor,
      overlay_opacity: overlayOpacity.toString(),
    });
    return typedApi.patch("/api/v1/user/holo-card/colors", {
      body,
      errorMessage: "Failed to update holo card colors",
    });
  },
};
