import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

export interface PersonalizationData {
  has_personalization?: boolean;
  house: House;
  personality_phrase: string;
  user_bio: string;
  account_number: number;
  member_since: string;
  overlay_color?: string;
  overlay_opacity?: number;
  suggested_workflows: Array<{
    id: string;
    title: string;
    description: string;
    steps: Array<{ category: string }>;
  }>;
}

interface UseOnboardingWebSocketReturn {
  personalizationData: PersonalizationData | null;
  isLoading: boolean;
  isComplete: boolean;
  intelligenceConversationId: string | null;
  isIntelligenceComplete: boolean;
}

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 1000;
const POLL_INTERVAL_MS = 5000;

export const useOnboardingWebSocket = (
  enabled: boolean = true,
): UseOnboardingWebSocketReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [intelligenceConversationId, setIntelligenceConversationId] = useState<
    string | null
  >(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const doneRef = useRef(false);

  // Keep ref in sync so callbacks can check without stale closures
  useEffect(() => {
    doneRef.current = !!intelligenceConversationId;
  }, [intelligenceConversationId]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    stopPolling();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [stopPolling]);

  // Poll API as fallback for intelligence completion
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;

    pollTimerRef.current = setInterval(async () => {
      if (doneRef.current) {
        stopPolling();
        return;
      }

      try {
        const data = await apiService.get<
          PersonalizationData & { first_message_conversation_id?: string }
        >("/onboarding/personalization", { silent: true });

        if (data.has_personalization) {
          setPersonalizationData(data);
          setIsLoading(false);
        }

        if (data.first_message_conversation_id) {
          setIntelligenceConversationId(data.first_message_conversation_id);
          stopPolling();
        }
      } catch {
        // Ignore — keep polling
      }
    }, POLL_INTERVAL_MS);
  }, [stopPolling]);

  // Main effect: connect WebSocket + check API on mount
  useEffect(() => {
    if (!enabled) return;

    const getWsUrl = () => {
      const apiBaseUrl =
        process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1/";
      return (
        apiBaseUrl.replace("http://", "ws://").replace("https://", "wss://") +
        "ws/connect"
      );
    };

    const connectWs = () => {
      if (doneRef.current) return;

      try {
        const ws = new WebSocket(getWsUrl());
        wsRef.current = ws;

        ws.onopen = () => {
          reconnectAttemptsRef.current = 0;
        };

        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data) as {
              type: string;
              data: PersonalizationData & { conversation_id?: string };
            };

            if (message.type === "onboarding_personalization_complete") {
              setPersonalizationData(message.data);
              setIsLoading(false);
              toast.success("Your personalized card is ready!");
            } else if (message.type === "onboarding_intelligence_complete") {
              const conversationId = message.data.conversation_id;
              if (conversationId) {
                setIntelligenceConversationId(conversationId);
                stopPolling();
              }
            }
          } catch (error) {
            console.error("Error parsing WebSocket message:", error);
          }
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (doneRef.current) return;

          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            const delay =
              RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttemptsRef.current;
            reconnectAttemptsRef.current += 1;
            reconnectTimerRef.current = setTimeout(connectWs, delay);
          } else {
            // Max reconnects exhausted — fall back to polling
            startPolling();
          }
        };

        ws.onerror = () => {
          // onclose fires after onerror, reconnect handled there
        };
      } catch {
        startPolling();
      }
    };

    // Check API immediately on mount (handles page reload / already-complete case)
    const checkOnMount = async () => {
      try {
        const data = await apiService.get<
          PersonalizationData & { first_message_conversation_id?: string }
        >("/onboarding/personalization", { silent: true });

        if (data.has_personalization) {
          setPersonalizationData(data);
          setIsLoading(false);
        }

        if (data.first_message_conversation_id) {
          setIntelligenceConversationId(data.first_message_conversation_id);
          return; // Already complete — no WebSocket needed
        }
      } catch {
        // Ignore, proceed with WebSocket
      }

      if (!doneRef.current) {
        connectWs();
      }
    };

    checkOnMount();

    return cleanup;
  }, [enabled, startPolling, stopPolling, cleanup]);

  return {
    personalizationData,
    isLoading,
    isComplete: !!personalizationData,
    intelligenceConversationId,
    isIntelligenceComplete: !!intelligenceConversationId,
  };
};
