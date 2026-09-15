export type { VoiceListResponse, VoiceOption } from "@shared/api/generated";

import { api } from "@/lib/api/typed";

export const voiceApi = {
  getVoices: () =>
    api.get("/api/v1/voice/voices", { errorMessage: "Failed to load voices" }),

  selectVoice: (voiceId: string) =>
    api.put("/api/v1/voice/voices/selected", {
      body: { voice_id: voiceId },
      errorMessage: "Failed to update voice",
    }),

  starVoice: (voiceId: string, starred: boolean) =>
    api.put("/api/v1/voice/voices/{voice_id}/star", {
      path: { voice_id: voiceId },
      body: { starred },
      errorMessage: "Failed to update starred voices",
    }),
};
