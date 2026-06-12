import { apiService } from "@/lib/api/service";

export interface VoiceOption {
  voice_id: string;
  name: string;
  language: string;
  accent: string;
  country_code: string;
  gender: string;
  description: string;
  preview_url: string | null;
  source: string;
  /** All verified languages (display names, primary first). */
  languages: string[];
  starred: boolean;
}

export interface VoiceListResponse {
  voices: VoiceOption[];
  selected_voice_id: string | null;
}

export const voiceApi = {
  getVoices: async (): Promise<VoiceListResponse> => {
    return apiService.get<VoiceListResponse>("/voice/voices", {
      errorMessage: "Failed to load voices",
    });
  },

  selectVoice: async (
    voiceId: string,
  ): Promise<{ selected_voice_id: string }> => {
    return apiService.put(
      "/voice/voices/selected",
      { voice_id: voiceId },
      { errorMessage: "Failed to update voice" },
    );
  },

  starVoice: async (
    voiceId: string,
    starred: boolean,
  ): Promise<{ starred_voice_ids: string[] }> => {
    return apiService.put(
      `/voice/voices/${voiceId}/star`,
      { starred },
      { errorMessage: "Failed to update starred voices" },
    );
  },
};
