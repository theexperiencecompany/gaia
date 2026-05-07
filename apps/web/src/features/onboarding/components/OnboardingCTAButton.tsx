/**
 * Shared raised CTA button for onboarding stage composers (e.g. "Looks good",
 * "Understood"). Defaults the trailing icon to `CircleArrowRight02Icon` and
 * forwards everything else to `RaisedButton`.
 */

"use client";

import { CircleArrowRight02Icon } from "@icons";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { cn } from "@/lib/utils";

interface OnboardingCTAButtonProps
  extends Omit<ComponentProps<typeof RaisedButton>, "children"> {
  children: ReactNode;
  endContent?: ReactNode;
  hideEndIcon?: boolean;
  href?: string;
}

export function OnboardingCTAButton({
  children,
  endContent,
  hideEndIcon = false,
  href,
  color = "#00bbff",
  className,
  ...props
}: OnboardingCTAButtonProps) {
  const mergedClassName = cn("text-black!", className);
  const content = (
    <>
      {children}
      {!hideEndIcon &&
        (endContent ?? <CircleArrowRight02Icon className="size-4" />)}
    </>
  );

  if (href) {
    return (
      <Link href={href} className="inline-flex">
        <RaisedButton
          color={color}
          className={mergedClassName}
          {...props}
          type="button"
        >
          {content}
        </RaisedButton>
      </Link>
    );
  }

  return (
    <RaisedButton color={color} className={mergedClassName} {...props}>
      {content}
    </RaisedButton>
  );
}
