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
  secondaryAction?: PromoBannerAction;
}

export function PromoBanner({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
}: PromoBannerProps) {
  const renderAction = (action: PromoBannerAction, isPrimary: boolean) => {
    const variant = action.variant ?? (isPrimary ? "solid" : "flat");
    const color = action.color ?? (isPrimary ? "primary" : "default");

    if (action.href) {
      return (
        <Button
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
        variant={variant}
        color={color}
        endContent={action.icon}
        onPress={action.onPress}
      >
        {action.label}
      </Button>
    );
  };

  return (
    <div className="relative overflow-hidden rounded-3xl bg-zinc-800/50">
      <div className="relative z-10 flex items-center justify-between gap-6 p-4">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/20">
            {icon}
          </div>
          <div>
            <h3 className="text-lg font-medium text-white">{title}</h3>
            <p className="text-sm text-zinc-400">{description}</p>
          </div>
        </div>

        <div className="flex shrink-0 gap-3">
          {secondaryAction && renderAction(secondaryAction, false)}
          {renderAction(primaryAction, true)}
        </div>
      </div>
    </div>
  );
}
