import type {
  PersonalizationResponse,
  PublicHoloCardResponse,
} from "@shared/api/generated";
import { api, FORM_URLENCODED_HEADERS } from "@/lib/api/typed";

export type HoloCardData = PersonalizationResponse;

export type PublicHoloCardData = PublicHoloCardResponse;

export const holoCardApi = {
  // Get current user's holo card data (authenticated) - includes workflows
  getMyHoloCard: () =>
    api.get("/api/v1/onboarding/personalization", { silent: true }),

  // Get public holo card data by card ID (no auth required) - no workflows
  getPublicHoloCard: (cardId: string) =>
    api.get("/api/v1/user/holo-card/{card_id}", { path: { card_id: cardId } }),

  // Update holo card colors (authenticated)
  updateHoloCardColors: (overlayColor: string, overlayOpacity: number) =>
    api.patch("/api/v1/user/holo-card/colors", {
      body: { overlay_color: overlayColor, overlay_opacity: overlayOpacity },
      headers: FORM_URLENCODED_HEADERS,
      errorMessage: "Failed to update holo card colors",
    }),
};
