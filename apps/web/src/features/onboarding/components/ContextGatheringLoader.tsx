"use client";

import { Spinner } from "@heroui/spinner";
import { Cancel01Icon } from "@icons";
import Image from "next/image";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components";
import { useUser } from "@/features/auth/hooks/useUser";
import type {
  PersonalizationData,
  PersonalizationProgressMessage,
} from "@/features/onboarding/types/websocket";
import {
  isBioStatusUpdateMessage,
  isPersonalizationCompleteMessage,
  isPersonalizationProgressMessage,
} from "@/features/onboarding/types/websocket";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";
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

export default function ContextGatheringLoader({
  onComplete,
}: ContextGatheringLoaderProps) {
  const user = useUser();
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const { phase, setPhase } = useOnboardingPhaseStore();
  const [isInitializing, setIsInitializing] = useState(true);
  const [progressData, setProgressData] = useState<
    PersonalizationProgressMessage["data"] | null
  >(null);

  const dismissalKey = `personalization-dismissed-${user.email || "unknown"}`;
  const isPersonalizationComplete =
    phase === OnboardingPhase.PERSONALIZATION_COMPLETE;
  const shouldHide =
    phase === OnboardingPhase.GETTING_STARTED ||
    phase === OnboardingPhase.COMPLETED;

  // Initialize: Fetch data and check if should hide
  useEffect(() => {
    const fetchPersonalization =
      async (): Promise<PersonalizationData | null> => {
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
      setProgressData(null); // Clear progress data

      // Only show success toast if not already shown
      if (
        personalizationData?.phase !== OnboardingPhase.PERSONALIZATION_COMPLETE
      ) {
        toast.success("Your personalized GAIA is ready! 🎉");
      }
    };

    const handleProgressUpdate = (message: unknown) => {
      if (!isPersonalizationProgressMessage(message)) return;
      setProgressData(message.data);
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
    wsManager.on("personalization_progress", handleProgressUpdate);
    wsManager.on("bio_status_update", handleBioStatusUpdate);

    return () => {
      wsManager.off(
        "onboarding_personalization_complete",
        handlePersonalizationComplete,
      );
      wsManager.off("personalization_progress", handleProgressUpdate);
      wsManager.off("bio_status_update", handleBioStatusUpdate);
    };
  }, [setPhase, personalizationData?.phase]);

  // Shared helper to handle phase transition
  const transitionToGettingStarted = async () => {
    try {
      // Update backend phase
      await apiService.post("/onboarding/phase", {
        phase: OnboardingPhase.GETTING_STARTED,
      });

      // Update local state
      localStorage.setItem(dismissalKey, "true");
      setPhase(OnboardingPhase.GETTING_STARTED);
    } catch (err) {
      console.error("Failed to transition phase:", err);
      // If it fails, we still want to update local state so user isn't stuck
      setPhase(OnboardingPhase.GETTING_STARTED);
      localStorage.setItem(dismissalKey, "true");
    }
  };

  // Handlers
  const handleDismiss = async () => {
    await transitionToGettingStarted();
  };

  const handleShowMeAround = async () => {
    // Open the modal first
    onComplete();
    // Then persist the state change
    await transitionToGettingStarted();
  };

  // Rendering helpers
  const getLoadingMessage = (): string => {
    // Use real progress message if available
    if (progressData?.message) {
      return progressData.message;
    }
    // Fallback to default
    return "✨ Preparing your magical space...";
  };

  const getProgressPercentage = (): number => {
    // Use real progress if available
    if (progressData?.progress !== undefined) {
      return progressData.progress;
    }
    // Fallback to 10%
    return 10;
  };

  const getProgressDetails = (): string | null => {
    if (!progressData?.details) return null;

    const { current, total, platforms } = progressData.details;

    // Show platforms found
    if (platforms && platforms.length > 0) {
      return platforms.join(", ");
    }

    // Show count progress as "blocks" for email scanning
    if (current !== undefined && total !== undefined) {
      // Use "blocks" terminology as requested
      return `${current}/${total} blocks`;
    }

    return null;
  };

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
  if (shouldHide) return null;

  // If no phase data and not initializing, show nothing (error state)
  if (!phase) return null;

  return (
    <div className="relative flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-2xl backdrop-blur-sm border-1 border-zinc-700/60 group">
      {/* Dismiss button - only show when personalization complete */}
      {isPersonalizationComplete && (
        <button
          onClick={handleDismiss}
          className="absolute top-2 right-2 rounded-full p-1 text-zinc-400 hover:bg-zinc-700 bg-zinc-800 hover:text-zinc-100 group-hover:opacity-100 opacity-0 transition cursor-pointer"
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
          <Image
            src={"/images/wallpapers/northernlights.webp"}
            alt="Beautiful Image"
            className="rounded-2xl max-h-30 object-cover object-bottom"
            width={1000}
            height={500}
          />

          <div className="flex flex-col items-start">
            <p className="font-medium text-zinc-100">Your GAIA is ready!</p>
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
        // Loading state: Show magical progress
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Spinner size="sm" variant="simple" />

            <div className="flex-1">
              <p className="text-xs font-medium text-zinc-300 transition-all duration-500">
                {getLoadingMessage()}
              </p>

              {getProgressDetails() && (
                <p className="mt-1 text-xs text-zinc-500 animate-fade-in">
                  {getProgressDetails()}
                </p>
              )}
            </div>
          </div>

          {/* Real progress bar */}
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-700">
            <div
              className="h-full rounded-full bg-primary transition-all duration-700 ease-out"
              style={{ width: `${getProgressPercentage()}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
