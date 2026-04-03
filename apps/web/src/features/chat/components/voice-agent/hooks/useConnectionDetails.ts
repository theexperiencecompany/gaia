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

export type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantToken: string;
  participantIdentity: string;
  participantName: string;
  agentToken: string;
};

const fetchDetails = async (
  conversationId?: string,
): Promise<ConnectionDetails> => {
  return apiService.get<ConnectionDetails>(
    conversationId ? `/token?conversationId=${conversationId}` : "/token",
    {
      errorMessage: "Failed to initiate livekit room",
    },
  );
};

export default function useConnectionDetails(
  conversationId?: string | undefined,
) {
  const queryClient = useQueryClient();
  const queryKey = ["connectionDetails", conversationId ?? "default"];

  const { data: connectionDetails = null } = useQuery({
    queryKey,
    queryFn: () => fetchDetails(conversationId),
    staleTime: 0, // Always considered stale so refresh logic works
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
