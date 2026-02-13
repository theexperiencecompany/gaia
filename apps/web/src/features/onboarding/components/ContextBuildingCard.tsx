"use client";

import { Card } from "@heroui/card";
import {
  Cancel01Icon,
  CheckmarkCircle02Icon,
  type IconProps,
  Loading02Icon,
} from "@icons";
import type { FC } from "react";
import {
  type ContextStatus,
  useOnboardingStore,
} from "@/stores/onboardingStore";

interface StatusConfig {
  text: string;
  color: string;
  spin: boolean;
  icon: FC<IconProps> | null;
}

const STATUS_CONFIG: Record<ContextStatus, StatusConfig> = {
  idle: { text: "Waiting...", icon: null, color: "text-white/50", spin: false },
  gathering: {
    text: "Gathering context...",
    icon: Loading02Icon,
    color: "text-blue-400",
    spin: true,
  },
  parsing_emails: {
    text: "Parsing emails...",
    icon: Loading02Icon,
    color: "text-blue-400",
    spin: true,
  },
  building_graph: {
    text: "Building memory graph...",
    icon: Loading02Icon,
    color: "text-purple-400",
    spin: true,
  },
  complete: {
    text: "Context ready!",
    icon: CheckmarkCircle02Icon,
    color: "text-green-400",
    spin: false,
  },
  error: {
    text: "Error occurred",
    icon: Cancel01Icon,
    color: "text-red-400",
    spin: false,
  },
};

export function ContextBuildingCard() {
  const { contextStatus, contextMessage } = useOnboardingStore();

  if (contextStatus === "idle") {
    return null;
  }

  const config = STATUS_CONFIG[contextStatus];
  const Icon = config.icon;

  return (
    <Card className="fixed right-4 bottom-[22rem] z-50 w-80 border border-white/10 bg-black/40 p-4 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        {Icon && (
          <Icon
            height={20}
            width={20}
            className={`${config.color} ${config.spin ? "animate-spin" : ""}`}
          />
        )}
        <div className="flex-1">
          <div className={`text-sm font-medium ${config.color}`}>
            {config.text}
          </div>
          {contextMessage && (
            <div className="mt-1 text-xs text-white/50">{contextMessage}</div>
          )}
        </div>
      </div>

      {(contextStatus === "gathering" ||
        contextStatus === "parsing_emails" ||
        contextStatus === "building_graph") && (
        <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-blue-400/50" />
        </div>
      )}
    </Card>
  );
}
