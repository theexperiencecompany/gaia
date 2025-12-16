import { useCallback, useEffect, useState } from "react";

import { apiService } from "@/lib/api";

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
export default function useConnectionDetails(
  conversationId?: string | undefined,
) {
  const [connectionDetails, setConnectionDetails] =
    useState<ConnectionDetails | null>(null);

  const fetchConnectionDetails = useCallback(async () => {
    setConnectionDetails(null);
    try {
      const data = await apiService.get<ConnectionDetails>(
        conversationId ? `/token?conversationId=${conversationId}` : "/token",
        {
          errorMessage: "Failed to initiate livekit room",
        },
      );
      setConnectionDetails(data);
      return data;
    } catch (error) {
      console.error("Error fetching connection details:", error);
      throw new Error("Error fetching connection details!");
    }
  }, [conversationId]);

  useEffect(() => {
    fetchConnectionDetails();
  }, [fetchConnectionDetails]);

  const isConnectionDetailsExpired = useCallback(() => {
    const token = connectionDetails?.participantToken;
    if (!token) {
      return true;
    }
    return isTokenExpired(token, ONE_MINUTE_IN_MILLISECONDS);
  }, [connectionDetails?.participantToken]);

  const existingOrRefreshConnectionDetails = useCallback(async () => {
    if (isConnectionDetailsExpired() || !connectionDetails) {
      return fetchConnectionDetails();
    } else {
      return connectionDetails;
    }
  }, [connectionDetails, fetchConnectionDetails, isConnectionDetailsExpired]);

  return {
    connectionDetails,
    refreshConnectionDetails: fetchConnectionDetails,
    existingOrRefreshConnectionDetails,
  };
}
