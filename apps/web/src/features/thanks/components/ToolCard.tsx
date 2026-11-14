"use client";

import { Tooltip } from "@heroui/tooltip";
import { GlobalIcon } from "@icons";
import { memo } from "react";
import type { Tool } from "@/data/tools";

interface ToolCardProps {
  tool: Tool;
}

const ToolCard = memo(({ tool }: ToolCardProps) => {
  return (
    <Tooltip
      showArrow
      delay={0}
      closeDelay={0}
      className="max-w-[320px] border-0 bg-zinc-900 p-0 text-white shadow-xl rounded-2xl overflow-hidden"
      content={
        <div className="flex w-full flex-col rounded-3xl">
          <div className="flex flex-col gap-2 p-4">
            <div className="flex items-center gap-2">
              <GlobalIcon className="h-5 w-5 text-zinc-400" />
              <span className="font-semibold text-white">{tool.name}</span>
            </div>

            <p className="text-sm leading-relaxed text-zinc-300">
              {tool.description}
            </p>

            <div className="mt-1 flex items-center gap-2">
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                {tool.category}
              </span>
            </div>

            <a
              href={tool.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 truncate text-xs text-primary hover:underline"
            >
              {tool.url.replace("https://", "").replace("http://", "")}
            </a>
          </div>
        </div>
      }
    >
      <a
        href={tool.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group flex items-center gap-3 rounded-2xl bg-zinc-900 px-4 py-3 transition-colors duration-200 hover:border-primary/50 hover:bg-zinc-800/50"
      >
        <div className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-zinc-800">
          <GlobalIcon className="h-5 w-5 text-zinc-500" />
        </div>
        <span className="font-medium text-zinc-200 transition-colors group-hover:text-white">
          {tool.name}
        </span>
      </a>
    </Tooltip>
  );
});

ToolCard.displayName = "ToolCard";

export default ToolCard;
