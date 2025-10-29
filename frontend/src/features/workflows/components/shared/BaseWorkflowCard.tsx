"use client";

import { ArrowUpRight } from "lucide-react";
import { ReactNode } from "react";

import { ToolsIcon } from "@/components";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

import { RunCountDisplay } from "./WorkflowCardComponents";

interface BaseWorkflowCardProps {
  title: string;
  description: string;
  steps?: Array<{ tool_category: string }>;
  integrations?: string[];
  onClick?: () => void;
  showArrowIcon?: boolean;
  headerRight?: ReactNode;
  footerContent?: ReactNode;
  triggerContent?: ReactNode;
  totalExecutions?: number;
  hideExecutions?: boolean;
  useBlurEffect?: boolean;
}

export default function BaseWorkflowCard({
  title,
  description,
  steps = [],
  integrations = [],
  onClick,
  showArrowIcon = false,
  headerRight,
  footerContent,
  triggerContent,
  totalExecutions = 0,
  hideExecutions = false,
  useBlurEffect = false,
}: BaseWorkflowCardProps) {
  const renderToolIcons = () => {
    let categories: string[];

    if (steps.length > 0)
      categories = [...new Set(steps.map((step) => step.tool_category))];
    else {
      // Handle integrations like in UseCaseCard
      const integrationToCategory: Record<string, string> = {
        gmail: "mail",
        gcal: "calendar",
        calendar: "calendar",
        gdocs: "google_docs",
        "google-docs": "google_docs",
        google_docs: "google_docs",
        notion: "notion",
        linear: "productivity",
        web: "search",
        "web search": "search",
        search: "search",
        mail: "mail",
        email: "mail",
        productivity: "productivity",
        documents: "documents",
        development: "development",
        memory: "memory",
        creative: "creative",
        weather: "weather",
        goal_tracking: "goal_tracking",
        webpage: "webpage",
        support: "support",
        general: "general",
      };
      categories = integrations.map(
        (integration) => integrationToCategory[integration] || integration,
      );
    }

    const validIcons = categories
      .slice(0, 5)
      .map((category, index) => {
        const IconComponent = getToolCategoryIcon(category, {
          width: 25,
          height: 25,
        });
        return IconComponent ? (
          <div
            key={category}
            className="relative flex items-center justify-center"
            style={{
              rotate:
                categories.length > 1
                  ? index % 2 == 0
                    ? "8deg"
                    : "-8deg"
                  : "0deg",
              zIndex: index,
            }}
          >
            {IconComponent}
          </div>
        ) : null;
      })
      .filter(Boolean);

    if (validIcons.length === 0 && categories.length > 0) {
      validIcons.push(
        <ToolsIcon width={25} height={25} className="text-foreground-400" />,
      );
    }

    return (
      <>
        <div className="flex min-h-8 -space-x-1.5">{validIcons}</div>
        {categories.length > 3 && (
          <div className="flex h-[25px] w-[25px] items-center justify-center rounded-lg bg-zinc-700 text-xs text-foreground-500">
            +{categories.length - 3}
          </div>
        )}
      </>
    );
  };

  return (
    <div
      className={`group relative z-[1] flex min-h-[140px] w-full flex-col gap-2 rounded-2xl outline-1 ${useBlurEffect ? "bg-zinc-800/40 outline-zinc-800/50 backdrop-blur-lg" : "bg-zinc-800 outline-zinc-800/70"} p-4 transition-all select-none ${
        onClick ? "cursor-pointer hover:bg-zinc-700/50" : ""
      }`}
      onClick={onClick}
    >
      {showArrowIcon && onClick && (
        <ArrowUpRight
          className="absolute top-4 right-4 text-foreground-400 opacity-0 transition group-hover:opacity-100"
          width={25}
          height={25}
        />
      )}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">{renderToolIcons()}</div>
        {headerRight}
      </div>

      <div>
        <h3 className="line-clamp-2 text-lg font-medium">{title}</h3>
        <div className="mt-1 line-clamp-2 min-h-8 flex-1 text-xs text-zinc-400">
          {description}
        </div>
      </div>

      <div className="mt-auto">
        {triggerContent && <div className="mt-1">{triggerContent}</div>}
        <div className="flex items-center justify-between gap-2">
          {!hideExecutions && (
            <RunCountDisplay totalExecutions={totalExecutions} />
          )}
          {footerContent && (
            <div className="flex-shrink-0">{footerContent}</div>
          )}
        </div>
      </div>
    </div>
  );
}
