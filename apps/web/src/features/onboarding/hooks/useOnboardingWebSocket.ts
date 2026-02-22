import { useEffect, useRef, useState } from "react";
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
}

export const useOnboardingWebSocket = (
  enabled: boolean = true,
): UseOnboardingWebSocketReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  // WebSocket listener
  useEffect(() => {
    if (!enabled || personalizationData) return;

    const apiBaseUrl =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1/";
    const wsUrl =
      apiBaseUrl.replace("http://", "ws://").replace("https://", "wss://") +
      "ws/connect";

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket connected for personalization");
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);

          if (message.type === "onboarding_personalization_complete") {
            console.log("Personalization data received:", message.data);
            setPersonalizationData(message.data);
            setIsLoading(false);
            toast.success("Your personalized card is ready! 🎉");
          }
        } catch (error) {
          console.error("Error parsing WebSocket message:", error);
        }
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
      };
    } catch (error) {
      console.error("Failed to connect WebSocket:", error);
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enabled, personalizationData]);

  // Fallback: Check API on mount to handle page reloads
  useEffect(() => {
    if (!enabled || personalizationData) return;

    const checkStatus = async () => {
      try {
        const data = await apiService.get<PersonalizationData>(
          "/onboarding/personalization",
          { silent: true },
        );

        // Only set if personalization is complete
        if (data.has_personalization) {
          setPersonalizationData(data);
          setIsLoading(false);
        }
      } catch (error) {
        // Ignore errors, wait for WebSocket
        console.error("Failed to check personalization status:", error);
      }
    };

    // Check immediately on mount (handles page reload case)
    checkStatus();
  }, [enabled, personalizationData]);

  return {
    personalizationData,
    isLoading,
    isComplete: !!personalizationData,
  };
};
