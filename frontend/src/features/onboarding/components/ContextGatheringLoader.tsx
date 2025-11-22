"use client";

import { Spinner } from "@heroui/spinner";
import { useEffect, useState } from "react";

import { RaisedButton } from "@/components";
import { usePersonalization } from "@/features/onboarding/hooks/usePersonalization";
import { Cancel01Icon } from '@/icons';

interface ContextGatheringLoaderProps {
  onComplete: () => void;
  duration?: number;
}

const DISMISSED_KEY = "onboarding-dismissed";

export default function ContextGatheringLoader({
  onComplete,
  duration = 5000,
}: ContextGatheringLoaderProps) {
  const [progress, setProgress] = useState(0);
  const [isDismissed, setIsDismissed] = useState(false);
  const { isComplete } = usePersonalization(true);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsDismissed(localStorage.getItem(DISMISSED_KEY) === "true");
    }
  }, []);

  useEffect(() => {
    if (isComplete) {
      setProgress(100);
      return;
    }

    const interval = setInterval(() => {
      setProgress((prev) => (prev >= 90 ? 90 : prev + 1));
    }, duration / 100);

    return () => clearInterval(interval);
  }, [duration, isComplete]);

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    setIsDismissed(true);
  };

  const handleShowMeAround = () => {
    onComplete();
    handleDismiss();
  };

  if (isDismissed) return null;

  return (
    <div className="relative flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
      {isComplete && (
        <button
          onClick={handleDismiss}
          className="absolute top-2 right-2 rounded-full p-1 text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-100"
          aria-label="Dismiss"
        >
          <Cancel01Icon size={16} />
        </button>
      )}

      {isComplete ? (
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
              className="h-full rounded-full bg-primary bg-gradient-to-r transition-all duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </>
      )}
    </div>
  );
}
