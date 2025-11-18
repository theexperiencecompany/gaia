import { Lock } from "lucide-react";
import React from "react";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

import { EnhancedToolInfo } from "../../types/enhancedTools";

interface LockedToolItemProps {
  tool: EnhancedToolInfo;
  onConnect?: () => void;
  showDescription?: boolean;
}

export const LockedToolItem: React.FC<LockedToolItemProps> = ({
  tool,
  onConnect,
  showDescription = true,
}) => {
  return (
    <div
      className="group relative mx-2 mb-1 cursor-pointer"
      onClick={onConnect}
    >
      {/* Overlay */}
      <div className="absolute inset-0 z-10" />

      {/* Tool content */}
      <div className="relative rounded-xl border border-transparent p-2">
        <div className="flex items-center gap-2">
          {/* Icon */}
          <div className="flex-shrink-0 blur-[2px] brightness-50 transition group-hover:blur-[0px] group-hover:brightness-100">
            {getToolCategoryIcon(tool.category)}
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm text-foreground-600 blur-[2px] brightness-50 transition group-hover:blur-[0px] group-hover:brightness-100">
                {formatToolName(tool.name)}
              </span>

              <div className="flex w-fit items-center gap-2">
                <Lock width={15} height={15} className="text-zinc-500" />
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 outline-1 outline-zinc-700">
                  {formatToolName(tool.category)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
