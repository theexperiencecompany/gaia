"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import type { ReactNode } from "react";

export interface PromoBannerAction {
  label: string;
  icon?: ReactNode;
  href?: string;
  onPress?: () => void;
  variant?: "flat" | "solid";
  color?: "default" | "primary";
}

export interface PromoBannerProps {
  icon: ReactNode;
  title: string;
  description: string;
  primaryAction: PromoBannerAction;
  /** Quieter alternatives, shown before the primary action. */
  secondaryActions?: PromoBannerAction[];
}

/** Renders a promo action as a link button when it has an href, else a press button. */
function renderAction(action: PromoBannerAction, isPrimary: boolean) {
  const variant = action.variant ?? (isPrimary ? "solid" : "flat");
  const color = action.color ?? (isPrimary ? "primary" : "default");

  if (action.href) {
    return (
      <Button
        key={action.label}
        as={Link}
        href={action.href}
        variant={variant}
        color={color}
        endContent={action.icon}
      >
        {action.label}
      </Button>
    );
  }

  return (
    <Button
      key={action.label}
      variant={variant}
      color={color}
      endContent={action.icon}
      onPress={action.onPress}
    >
      {action.label}
    </Button>
  );
}

export function PromoBanner({
  icon,
  title,
  description,
  primaryAction,
  secondaryActions = [],
}: PromoBannerProps) {
  return (
    <div className="relative overflow-hidden rounded-3xl bg-zinc-800/50">
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="flex min-w-72 flex-1 items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/20">
            {icon}
          </div>
          <div>
            <h3 className="text-lg font-medium text-white">{title}</h3>
            <p className="text-sm text-zinc-400">{description}</p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-3">
          {secondaryActions.map((action) => renderAction(action, false))}
          {renderAction(primaryAction, true)}
        </div>
      </div>
    </div>
  );
}
