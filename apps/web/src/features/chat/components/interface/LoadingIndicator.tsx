"use client";

import { AnimatePresence, motion } from "framer-motion";

import { WaveSpinnerSquare } from "@/components/shared/WaveSpinnerSquare";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface LoadingIndicatorProps {
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: {
    toolCategory?: string;
    integrationName?: string;
    iconUrl?: string;
    showCategory?: boolean;
  };
}

const slideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

const transition = {
  duration: 0.15,
  ease: [0.32, 0.72, 0, 1] as const,
};

function formatCategoryName(category: string): string {
  return category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function LoadingIndicator({
  loadingText,
  loadingTextKey,
  toolInfo,
}: LoadingIndicatorProps) {
  const prefix =
    toolInfo?.showCategory !== false && toolInfo?.toolCategory
      ? `${toolInfo.integrationName || formatCategoryName(toolInfo.toolCategory)}: `
      : "";

  return (
    <motion.div
      className="flex items-center gap-4 pl-11 text-sm font-medium"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={transition}
    >
      {(toolInfo?.toolCategory &&
        getToolCategoryIcon(
          toolInfo.toolCategory,
          { size: 20, width: 20, height: 20, iconOnly: true },
          toolInfo.iconUrl,
        )) || <WaveSpinnerSquare />}
      <AnimatePresence mode="wait">
        <motion.span
          key={loadingTextKey}
          variants={slideUp}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={transition}
          className="animate-shine bg-size-[200%_100%] bg-clip-text text-transparent w-fit"
          style={{
            backgroundImage:
              "linear-gradient(90deg, rgb(255 255 255 / 0.3) 20%, rgb(255 255 255) 50%, rgb(255 255 255 / 0.3) 80%)",
          }}
        >
          {prefix}
          {loadingText || "GAIA is thinking..."}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  );
}
