"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type VoiceListResponse,
  voiceApi,
} from "@/features/settings/api/voiceApi";
import { toast } from "@/lib/toast";

const VOICES_QUERY_KEY = ["voice-settings", "voices"];

export function useVoices() {
  return useQuery({
    queryKey: VOICES_QUERY_KEY,
    queryFn: voiceApi.getVoices,
    staleTime: 5 * 60 * 1000,
  });
}

export function useStarVoice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ voiceId, starred }: { voiceId: string; starred: boolean }) =>
      voiceApi.starVoice(voiceId, starred),
    onMutate: async ({ voiceId, starred }) => {
      await queryClient.cancelQueries({ queryKey: VOICES_QUERY_KEY });
      const previous =
        queryClient.getQueryData<VoiceListResponse>(VOICES_QUERY_KEY);
      if (previous) {
        queryClient.setQueryData<VoiceListResponse>(VOICES_QUERY_KEY, {
          ...previous,
          voices: previous.voices.map((v) =>
            v.voice_id === voiceId ? { ...v, starred } : v,
          ),
        });
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(VOICES_QUERY_KEY, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: VOICES_QUERY_KEY });
    },
  });
}

export function useSelectVoice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: voiceApi.selectVoice,
    onMutate: async (voiceId: string) => {
      await queryClient.cancelQueries({ queryKey: VOICES_QUERY_KEY });
      const previous =
        queryClient.getQueryData<VoiceListResponse>(VOICES_QUERY_KEY);
      if (previous) {
        queryClient.setQueryData<VoiceListResponse>(VOICES_QUERY_KEY, {
          ...previous,
          selected_voice_id: voiceId,
        });
      }
      return { previous };
    },
    onError: (_error, _voiceId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(VOICES_QUERY_KEY, context.previous);
      }
    },
    onSuccess: (_data, voiceId, context) => {
      const name = context?.previous?.voices.find(
        (v) => v.voice_id === voiceId,
      )?.name;
      toast.success(name ? `Voice set to ${name}` : "Voice updated");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: VOICES_QUERY_KEY });
    },
  });
}
