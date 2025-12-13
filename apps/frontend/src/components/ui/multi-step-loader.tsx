"use client";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

import { CheckmarkCircle02Icon } from "@/icons";
import { cn } from "@/lib/utils";

type LoadingState = {
  text: string;
};

const LoaderCore = ({
  loadingStates,
  value = 0,
}: {
  loadingStates: LoadingState[];
  value?: number;
}) => {
  return (
    <div className="relative mx-auto mt-40 flex max-w-xl flex-col justify-start">
      {loadingStates.map((loadingState, index) => {
        const distance = Math.abs(index - value);
        const opacity = Math.max(1 - distance * 0.2, 0); // Minimum opacity is 0, keep it 0.2 if you're sane.

        return (
          <motion.div
            key={loadingState.text}
            animate={{ opacity: opacity, y: -(value * 40) }}
            className={cn("mb-4 flex gap-2 text-left")}
            initial={{ opacity: 0, y: -(value * 40) }}
            transition={{ duration: 0.5 }}
          >
            <div>
              {index > value && (
                <CheckmarkCircle02Icon className="text-gray-600" />
              )}
              {index <= value && (
                <CheckmarkCircle02Icon
                  className={cn(
                    "text-gray-600",
                    value === index && "text-green-500 opacity-100",
                  )}
                />
              )}
            </div>
            <span
              className={cn(
                "text-gray-600",
                value === index && "text-green-500 opacity-100",
              )}
            >
              {loadingState.text}
            </span>
          </motion.div>
        );
      })}
    </div>
  );
};

export const MultiStepLoader = ({
  loadingStates,
  loading,
  duration = 2000,
  loop = true,
}: {
  loadingStates: LoadingState[];
  loading?: boolean;
  duration?: number;
  loop?: boolean;
}) => {
  const [currentState, setCurrentState] = useState(0);

  useEffect(() => {
    if (!loading) {
      setCurrentState(0);

      return;
    }
    const timeout = setTimeout(() => {
      setCurrentState((prevState) =>
        loop
          ? prevState === loadingStates.length - 1
            ? 0
            : prevState + 1
          : Math.min(prevState + 1, loadingStates.length - 1),
      );
    }, duration);

    return () => clearTimeout(timeout);
  }, [currentState, loading, loop, loadingStates.length, duration]);

  return (
    <AnimatePresence mode="wait">
      {loading && (
        <motion.div
          animate={{
            opacity: 1,
          }}
          className="flex items-center justify-center"
          exit={{
            opacity: 0,
          }}
          initial={{
            opacity: 0,
          }}
        >
          <div className="relative h-[300px]">
            <LoaderCore loadingStates={loadingStates} value={currentState} />
          </div>

          {/* <div className="bg-linear-to-t inset-x-0 z-20 bottom-0 bg-white dark:bg-black h-full absolute [mask-image:radial-gradient(900px_at_center,transparent_30%,white)]" /> */}
        </motion.div>
      )}
    </AnimatePresence>
  );
};
