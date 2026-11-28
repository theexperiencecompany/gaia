import { SquareLock01Icon } from "@icons";
import type React from "react";
import type { ToolInfo } from "@/features/chat/api/toolsApi";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";

interface LockedToolItemProps {
  tool: Pick<ToolInfo, "name" | "category" | "display_name" | "icon_url">;
  onConnect?: () => void;
}

export const LockedToolItem: React.FC<LockedToolItemProps> = ({
  tool,
  onConnect,
}) => {
  return (
    <button
      type="button"
      aria-label={`Connect ${tool.display_name} to use ${formatToolName(tool.name)}`}
      className="group relative mx-2 mb-1 block w-[calc(100%_-_1rem)] cursor-pointer text-left"
      onClick={onConnect}
    >
      {/* Overlay */}
      <div className="absolute inset-0 z-10" />

      {/* Tool content */}
      <div className="relative rounded-xl border border-transparent p-2">
        <div className="flex items-center gap-2">
          {/* Icon */}
          <div className="flex-shrink-0 blur-[2px] brightness-50 transition group-hover:blur-[0px] group-hover:brightness-100">
            <IntegrationIcon
              integrationId={tool.category}
              iconUrl={tool.icon_url}
              size={20}
              showBackground
            />
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm text-zinc-300 blur-[2px] brightness-50 transition group-hover:blur-[0px] group-hover:brightness-100">
                {formatToolName(tool.name)}
              </span>

              <div className="flex w-fit items-center gap-2">
                <SquareLock01Icon
                  width={15}
                  height={15}
                  className="text-zinc-500"
                />
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 outline-1 outline-zinc-700">
                  {tool.display_name}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </button>
  );
};
