import { Cancel01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { useEffect, useRef } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useComposerUI } from "@/stores/composerStore";

interface SelectedToolIndicatorProps {
  toolName: string | null;
  toolCategory?: string | null;
  iconUrl?: string | null;
  onRemove?: () => void;
}

const TOOL_SUFFIX_REGEX = / tool$/i;

const formatToolName = (toolName: string): string => {
  return toolName
    .toLowerCase() // First convert to lowercase
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ")
    .replace(TOOL_SUFFIX_REGEX, "") // Remove "Tool" suffix (case insensitive)
    .trim();
};

const SelectedToolIndicator: React.FC<SelectedToolIndicatorProps> = ({
  toolName,
  toolCategory,
  iconUrl,
  onRemove,
}) => {
  const { isSlashCommandDropdownOpen } = useComposerUI();

  const onRemoveRef = useRef(onRemove);
  onRemoveRef.current = onRemove;
  const isSlashCommandOpenRef = useRef(isSlashCommandDropdownOpen);
  isSlashCommandOpenRef.current = isSlashCommandDropdownOpen;

  // Handle Escape key to close the indicator
  useEffect(() => {
    if (!toolName) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle escape if slash command dropdown is NOT open
      if (e.key === "Escape" && !isSlashCommandOpenRef.current) {
        e.preventDefault();
        onRemoveRef.current?.();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toolName]);

  return (
    <AnimatePresence>
      {toolName && (
        <m.div
          initial={{ opacity: 0, scale: 0.9, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          // exit={{ opacity: 0, scale: 0.9, y: 10 }}
          transition={{
            type: "spring",
            damping: 20,
            stiffness: 300,
            duration: 0.2,
          }}
          className="mx-3 mt-2 mb-1 flex w-fit items-center gap-2 rounded-xl bg-zinc-700 px-2 py-1 pl-1"
        >
          <div>
            {getToolCategoryIcon(
              toolCategory || "general",
              {
                size: 17,
              },
              iconUrl,
            )}
          </div>
          <span className="text-sm font-light text-zinc-200">
            {formatToolName(toolName)}
          </span>
          {onRemove && (
            <m.button
              onClick={onRemove}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-600 hover:text-zinc-200"
            >
              <Cancel01Icon size={15} />
            </m.button>
          )}
        </m.div>
      )}
    </AnimatePresence>
  );
};

export default SelectedToolIndicator;
