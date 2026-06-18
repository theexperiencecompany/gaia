import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { apiService } from "@/lib/api/service";

function decodeJwtPayload(token: string) {
  if (!token) return {};
  const payload = token.split(".")[1];
  // Add padding if needed
  const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(
    base64.length + ((4 - (base64.length % 4)) % 4),
    "=",
  );
  const decoded = atob(padded);
  return JSON.parse(decoded);
}

function isTokenExpired(token: string, offsetMs = 60000) {
  const payload = decodeJwtPayload(token);
  if (!payload.exp) return true;
  const expiresAt = payload.exp * 1000 - offsetMs;
  return Date.now() > expiresAt;
}

const ONE_MINUTE_IN_MILLISECONDS = 60 * 1000;

/**
 * How long a fetched token is reused without a refetch. Tokens live much
 * longer than this; the JWT-expiry guard below still forces a refresh for a
 * genuinely stale token. Non-zero so an intent prefetch (e.g. hovering the
 * voice button) is actually consumed by the session instead of double-minting
 * — every /token call burns a voice_mode rate-limit credit.
 */
const CONNECTION_DETAILS_STALE_TIME_MS = 2 * 60 * 1000;

/** Response of GET /token — mirrors the backend's VoiceTokenResponse schema. */
export type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantToken: string;
  participantIdentity: string;
  participantName: string;
  conversation_id: string | null;
};

const fetchDetails = async (
  conversationId?: string,
  // Hover-intent prefetch is best-effort background work — suppress its toast so
  // a failed prefetch never surfaces a user-facing error (the foreground session
  // start still toasts on failure).
  silent = false,
): Promise<ConnectionDetails> => {
  return apiService.get<ConnectionDetails>(
    conversationId ? `/token?conversationId=${conversationId}` : "/token",
    {
      errorMessage: "Failed to initiate livekit room",
      silent,
    },
  );
};

/**
 * Prefetch the session token on intent (voice-button hover) so the actual
 * session start consumes the cached result instead of paying the /token
 * round trip. Callers must gate on subscription — the endpoint is
 * rate-limited per plan.
 */
export function usePrefetchConnectionDetails(conversationId?: string) {
  const queryClient = useQueryClient();
  return useCallback(() => {
    queryClient
      .prefetchQuery({
        queryKey: ["connectionDetails", conversationId ?? "default"],
        queryFn: () => fetchDetails(conversationId, true),
        staleTime: CONNECTION_DETAILS_STALE_TIME_MS,
      })
      .catch(() => {});
  }, [queryClient, conversationId]);
}

export default function useConnectionDetails(
  conversationId?: string | undefined,
) {
  const queryClient = useQueryClient();
  const queryKey = ["connectionDetails", conversationId ?? "default"];

  const { data: connectionDetails = null } = useQuery({
    queryKey,
    queryFn: () => fetchDetails(conversationId),
    staleTime: CONNECTION_DETAILS_STALE_TIME_MS,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: true,
  });

  const refreshConnectionDetails = useCallback(async () => {
    const result = await queryClient.fetchQuery({
      queryKey,
      queryFn: () => fetchDetails(conversationId),
      staleTime: 0,
    });
    return result;
  }, [queryClient, queryKey, conversationId]);

  const isConnectionDetailsExpired = useCallback(() => {
    const token = connectionDetails?.participantToken;
    if (!token) {
      return true;
    }
    return isTokenExpired(token, ONE_MINUTE_IN_MILLISECONDS);
  }, [connectionDetails?.participantToken]);

  const existingOrRefreshConnectionDetails = useCallback(async () => {
    if (isConnectionDetailsExpired() || !connectionDetails) {
      return refreshConnectionDetails();
    }
    return connectionDetails;
  }, [connectionDetails, refreshConnectionDetails, isConnectionDetailsExpired]);

  return {
    connectionDetails,
    refreshConnectionDetails,
    existingOrRefreshConnectionDetails,
  };
}
