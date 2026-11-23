"use client";

import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NOTIFICATION_CHANNEL_LABELS } from "@/features/notification/constants";
import {
  channelPreferencesQuery,
  preferencesApi,
} from "@/features/settings/api/preferencesApi";
import { preferenceKeys } from "@/features/settings/api/queryKeys";
import { toast } from "@/lib/toast";

interface ChannelToggle {
  channel: ChannelPlatform;
  enabled: boolean;
}

/**
 * The user's stored channel switches, each flipped at once and rolled back if
 * the save fails. Null until loaded: a stand-in would show a channel the user
 * switched off as on, and toggling from that reading writes the wrong value.
 */
export function useChannelPreferences() {
  const qc = useQueryClient();
  const { data, isError, refetch } = useQuery(channelPreferencesQuery());

  const mutation = useMutation({
    mutationFn: ({ channel, enabled }: ChannelToggle) =>
      preferencesApi.updateChannel(channel, enabled),
    onMutate: async ({ channel, enabled }) => {
      await qc.cancelQueries({ queryKey: preferenceKeys.channels });
      const previous = qc.getQueryData<ChannelPreferences>(
        preferenceKeys.channels,
      );
      if (previous)
        qc.setQueryData(preferenceKeys.channels, {
          ...previous,
          [channel]: enabled,
        });
      return { previous };
    },
    onError: (_error, { channel }, context) => {
      qc.setQueryData(preferenceKeys.channels, context?.previous);
      toast.error(
        `Couldn't update ${NOTIFICATION_CHANNEL_LABELS[channel]} notifications`,
      );
    },
    onSuccess: (stored) => qc.setQueryData(preferenceKeys.channels, stored),
  });

  return {
    preferences: data ?? null,
    loadFailed: isError,
    refetch: () => void refetch(),
    toggle: (channel: ChannelPlatform, enabled: boolean) =>
      mutation.mutate({ channel, enabled }),
  };
}
