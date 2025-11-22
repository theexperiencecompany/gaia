"use client";

import { Spinner } from "@heroui/spinner";
import { useEffect, useState } from "react";

import { RaisedButton } from "@/components";
import { usePersonalization } from "@/features/onboarding/hooks/usePersonalization";
import { Cancel01Icon } from "@/icons";

/**
 * ContextGatheringLoader - Shows personalization progress
 *
 * This component handles the SECOND phase of onboarding:
 * 1. Initial Onboarding (name/profession/connections) - handled on /onboarding page
 * 2. Personalization (house assignment, bio generation) - THIS COMPONENT ✓
 * 3. Getting Started steps (create email, calendar, etc.) - separate component
 *
 * The personalization happens in the background after initial onboarding is complete.
 * This card shows progress and triggers the holo card modal when ready.
 */

interface ContextGatheringLoaderProps {
  onComplete: () => void;
}

const PERSONALIZATION_DISMISSED_KEY = "personalization-card-dismissed";
const PROGRESS_INTERVAL_MS = 300; // Update progress every 300ms

export default function ContextGatheringLoader({
  onComplete,
}: ContextGatheringLoaderProps) {
  const [progress, setProgress] = useState(0);
  const [isDismissed, setIsDismissed] = useState(false);
  const { isComplete: hasPersonalization, isLoading } =
    usePersonalization(true);

  console.log(
    "[ContextGatheringLoader] hasPersonalization:",
    hasPersonalization,
    "isLoading:",
    isLoading,
  );

  // Check if user previously dismissed the completed personalization card
  useEffect(() => {
    if (typeof window !== "undefined") {
      const dismissed =
        localStorage.getItem(PERSONALIZATION_DISMISSED_KEY) === "true";
      console.log(
        "[ContextGatheringLoader] Dismissed state from localStorage:",
        dismissed,
      );
      setIsDismissed(dismissed);
    }
  }, []);

  // Smooth progress animation
  useEffect(() => {
    if (hasPersonalization) {
      setProgress(100);
      return;
    }

    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 95) return 95; // Cap at 95% until actually complete
        return prev + 1;
      });
    }, PROGRESS_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [hasPersonalization]);

  const handleDismiss = () => {
    localStorage.setItem(PERSONALIZATION_DISMISSED_KEY, "true");
    setIsDismissed(true);
  };

  const handleShowMeAround = () => {
    onComplete();
    handleDismiss();
  };

  // Only hide if user explicitly dismissed the completed personalization card
  if (isDismissed) return null;

  return (
    <div className="relative flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
      {hasPersonalization && (
        <button
          onClick={handleDismiss}
          className="absolute top-2 right-2 rounded-full p-1 text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-100"
          aria-label="Dismiss"
        >
          <Cancel01Icon size={16} />
        </button>
      )}

      {hasPersonalization ? (
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
        <>
          <div className="flex items-center gap-3">
            <Spinner size="sm" variant="simple" />
            <div className="flex-1">
              <p className="text-xs font-medium text-zinc-300">
                Gathering context for personalized card...
              </p>
            </div>
          </div>

          <div className="h-1 w-full overflow-hidden rounded-full bg-zinc-700">
            <div
              className="h-full rounded-full bg-primary bg-gradient-to-r transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </>
      )}
    </div>
  );
}
