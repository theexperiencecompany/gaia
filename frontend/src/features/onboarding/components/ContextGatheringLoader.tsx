"use client";

import { RaisedButton } from "@/components";
import { Spinner } from "@heroui/spinner";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

interface ContextGatheringLoaderProps {
  onComplete: () => void;
  duration?: number;
}

export default function ContextGatheringLoader({
  onComplete,
  duration = 5000,
}: ContextGatheringLoaderProps) {
  const [isComplete, setIsComplete] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setIsComplete(true);
          return 100;
        }
        return prev + 1;
      });
    }, duration / 100);

    return () => clearInterval(interval);
  }, [duration]);

  return (
    <div className="flex flex-col justify-center gap-3 rounded-2xl bg-zinc-800/90 p-4 shadow-xl backdrop-blur-sm">
      {isComplete ? (
        <>
          <div className="flex flex-col items-start">
            <p className="font-medium text-zinc-100">Your GAIA is ready</p>
            <p className="text-xs text-zinc-400">
              Let's explore what I can do for you
            </p>
          </div>

          <RaisedButton
            onClick={onComplete}
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
                Gathering context for memory graph...
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
