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
};
