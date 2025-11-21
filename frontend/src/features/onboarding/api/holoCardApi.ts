import { PersonalizationData } from "@/features/onboarding/hooks/useOnboardingWebSocket";
import { apiService } from "@/lib/api";
import { api } from "@/lib/api/client";

export interface HoloCardData extends PersonalizationData {
  name: string;
  holo_card_id?: string;
}

export interface PublicHoloCardData {
  house: string;
  personality_phrase: string;
  user_bio: string;
  account_number: number;
  member_since: string;
  name: string;
  overlay_color?: string;
  overlay_opacity?: number;
}

export const holoCardApi = {
  // Get current user's holo card data (authenticated) - includes workflows
  getMyHoloCard: async (): Promise<HoloCardData> => {
    return apiService.get<HoloCardData>("/oauth/onboarding/personalization", {
      silent: true,
    });
  },

  // Get public holo card data by card ID (no auth required) - no workflows
  getPublicHoloCard: async (cardId: string): Promise<PublicHoloCardData> => {
    const response = await api.get<PublicHoloCardData>(
      `/oauth/holo-card/${cardId}`,
    );
    return response.data;
  },

  // Update holo card colors (authenticated)
  updateHoloCardColors: async (
    overlayColor: string,
    overlayOpacity: number,
  ): Promise<{ success: boolean; message: string }> => {
    const formData = new FormData();
    formData.append("overlay_color", overlayColor);
    formData.append("overlay_opacity", overlayOpacity.toString());

    return apiService.patch("/oauth/holo-card/colors", formData, {
      errorMessage: "Failed to update holo card colors",
    });
  },
};
