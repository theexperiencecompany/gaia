"use client";

import { Spinner } from "@heroui/spinner";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RaisedButton } from "@/components";
import { useUser } from "@/features/auth/hooks/useUser";
import type {
  PersonalizationData,
} from "@/features/onboarding/types/websocket";
import {
  isBioStatusUpdateMessage,
  isPersonalizationCompleteMessage,
} from "@/features/onboarding/types/websocket";
import { Cancel01Icon } from "@/icons";
import { apiService } from "@/lib/api";
import { wsManager } from "@/lib/websocket";
import {
  OnboardingPhase,
  useOnboardingPhaseStore,
} from "@/stores/onboardingStore";

/**
 * ContextGatheringLoader - Personalization progress card
 *
 * Shows during the personalization phase of onboarding:
 * - PERSONALIZATION_PENDING: Shows loading state with progress
 * - PERSONALIZATION_COMPLETE: Shows "Show me around" button
 *
 * Data sources:
 * - Initial load: Fetches from API on mount
 * - Updates: WebSocket event when personalization completes
 * - Page reload: Fresh API fetch on mount
 *
 * No polling needed - WebSocket provides real-time updates,
 * and page reload/navigation fetches fresh data.
 */

interface ContextGatheringLoaderProps {
  onComplete: () => void;
}

const LOADING_MESSAGES = [
  "Creating your personalized space...",
  "Assigning your GAIA house...",
  "Generating your personality profile...",
  "Preparing your workspace...",
] as const;


const MAX_PROGRESS_TIME_SECONDS = 30;
const MESSAGE_ROTATION_INTERVAL_SECONDS = 3;

export default function ContextGatheringLoader({
  onComplete,
}: ContextGatheringLoaderProps) {
  const user = useUser();
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const { phase, setPhase } = useOnboardingPhaseStore();
  const [isInitializing, setIsInitializing] = useState(true);
  const [messageIndex, setMessageIndex] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const dismissalKey = `personalization-dismissed-${user.email || "unknown"}`;
  const isPersonalizationComplete =
    phase === OnboardingPhase.PERSONALIZATION_COMPLETE;
  const isLoading = phase === OnboardingPhase.PERSONALIZATION_PENDING;
  const shouldHide =
    phase === OnboardingPhase.GETTING_STARTED ||
    phase === OnboardingPhase.COMPLETED;

  // Initialize: Fetch data and check if should hide
  useEffect(() => {
    const fetchPersonalization = async (): Promise<PersonalizationData | null> => {
      try {
        const data = await apiService.get<PersonalizationData>(
          "/onboarding/personalization",
          { silent: true },
        );

        setPersonalizationData(data);
        if (data?.phase) setPhase(data.phase as OnboardingPhase);

        return data;
      } catch {
        return null;
      }
    };

    const initialize = async () => {
      const data = await fetchPersonalization();

      // Auto-hide if user already completed personalization
      if (
        data?.phase === OnboardingPhase.GETTING_STARTED ||
        data?.phase === OnboardingPhase.COMPLETED
      ) {
        setIsInitializing(false);
        return;
      }

      // Check localStorage dismissal (backup check)
      if (typeof window !== "undefined") {
        const wasDismissed = localStorage.getItem(dismissalKey) === "true";
        if (
          wasDismissed &&
          data?.phase !== OnboardingPhase.PERSONALIZATION_PENDING
        ) {
          setIsInitializing(false);
          return;
        }
      }

      setIsInitializing(false);
    };

    initialize();
  }, [dismissalKey, setPhase]);

  // WebSocket: Listen for completion event
  useEffect(() => {
    const handlePersonalizationComplete = (message: unknown) => {
      if (!isPersonalizationCompleteMessage(message)) return;

      const updatedData: PersonalizationData = {
        ...message.data,
        has_personalization: true,
        phase: OnboardingPhase.PERSONALIZATION_COMPLETE,
      };

      setPersonalizationData(updatedData);
      setPhase(OnboardingPhase.PERSONALIZATION_COMPLETE);

      toast.success("Your personalized GAIA is ready! 🎉");
    };

    const handleBioStatusUpdate = (message: unknown) => {
      if (!isBioStatusUpdateMessage(message)) return;


      // If bio status changed to processing, reset the personalization state
      if (message.data.bio_status === "processing") {
        setPhase(OnboardingPhase.PERSONALIZATION_PENDING);
        setPersonalizationData((prev) => ({
          ...prev,
          phase: OnboardingPhase.PERSONALIZATION_PENDING,
          has_personalization: false,
        }));

        // Show a message that Gmail processing has started
        toast.info(
          "Processing your Gmail data... This may take a few minutes.",
        );
      }
    };

    wsManager.on(
      "onboarding_personalization_complete",
      handlePersonalizationComplete,
    );
    wsManager.on("bio_status_update", handleBioStatusUpdate);

    return () => {
      wsManager.off(
        "onboarding_personalization_complete",
        handlePersonalizationComplete,
      );
      wsManager.off("bio_status_update", handleBioStatusUpdate);
    };
  }, [setPhase]);

  // Timer: Progress bar and message rotation
  useEffect(() => {
    if (!isLoading) {
      setMessageIndex(0);
      setElapsedSeconds(0);
      return;
    }

    const timer = setInterval(() => {
      setElapsedSeconds((prev) => {
        const newTime = prev + 1;

        // Rotate message every 3 seconds
        if (newTime > 0 && newTime % MESSAGE_ROTATION_INTERVAL_SECONDS === 0) {
          setMessageIndex(
            (prevIndex) => (prevIndex + 1) % LOADING_MESSAGES.length,
          );
        }

        return newTime;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isLoading]);

  // Handlers
  const handleDismiss = () => {
    if (phase !== OnboardingPhase.PERSONALIZATION_COMPLETE) return;

    localStorage.setItem(dismissalKey, "true");
    setPhase(OnboardingPhase.GETTING_STARTED);
  };

  const handleShowMeAround = async () => {
    try {
      // Update backend phase
      await apiService.post("/onboarding/phase", {
        phase: OnboardingPhase.GETTING_STARTED,
      });

      // Save dismissal state
      localStorage.setItem(dismissalKey, "true");
      // Update global store immediately
      setPhase(OnboardingPhase.GETTING_STARTED);

      onComplete();
    } catch {
      toast.error("Failed to update progress. Please try again.");
    }
  };

  // Rendering helpers
  const getLoadingMessage = (): string => {
    if (!personalizationData) return LOADING_MESSAGES[0];

    return LOADING_MESSAGES[messageIndex] || LOADING_MESSAGES[0];
  };

  const getProgressPercentage = (): number => {
    // Cap at 95% to show it's still processing
    const progress = Math.min(
      (elapsedSeconds / MAX_PROGRESS_TIME_SECONDS) * 100,
      95,
    );
    return progress;
  };

  const shouldShowGmailHint =
    personalizationData?.bio_status === "no_gmail" && elapsedSeconds > 2;

  // Show loading state during initialization
  if (isInitializing) {
    return (
      <div className="relative flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <Spinner size="sm" variant="simple" />
          <p className="text-xs font-medium text-zinc-300">
            Initializing your personalization...
          </p>
        </div>
      </div>
    );
  }

  // Hide if personalization is complete or user dismissed
  if (shouldHide)
    return null;

  // If no phase data and not initializing, show nothing (error state)
  if (!phase)
    return null;

  return (
    <div className="relative flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
      {/* Dismiss button - only show when personalization complete */}
      {isPersonalizationComplete && (
        <button
          onClick={handleDismiss}
          className="absolute top-2 right-2 rounded-full p-1 text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-100"
          aria-label="Dismiss"
          type="button"
        >
          <Cancel01Icon size={16} />
        </button>
      )}

      {/* Content */}
      {isPersonalizationComplete ? (
        // Ready state: Show "Show me around" button
        <>
          <div className="flex flex-col items-start">
            <p className="font-medium text-zinc-100">Your GAIA is ready</p>
            <p className="text-xs text-zinc-400">
              Let's explore what I can do for you
            </p>
          </div>

          <RaisedButton
            onClick={handleShowMeAround}
            color="#00bbff"
            className="text-black!"
          >
            Show me around
          </RaisedButton>
        </>
      ) : (
        // Loading state: Show progress
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Spinner size="sm" variant="simple" />

            <div className="flex-1">
              <p className="text-xs font-medium text-zinc-300 transition-all duration-500">
                {getLoadingMessage()}
              </p>

              {shouldShowGmailHint && (
                <p className="animate-fade-in mt-1 text-xs text-zinc-500">
                  Connect Gmail later for personalized insights
                </p>
              )}
            </div>
          </div>

          {/* Progress bar */}
          <div className="h-1 w-full overflow-hidden rounded-full bg-zinc-700">
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-1000"
              style={{ width: `${getProgressPercentage()}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
