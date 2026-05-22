/**
 * Shared raised CTA button for onboarding stage composers (e.g. "Looks good",
 * "Understood"). Defaults the trailing icon to `CircleArrowRight02Icon` and
 * forwards everything else to `RaisedButton`. When `href` is set the button
 * navigates via the router instead of nesting inside a <Link> — RaisedButton
 * renders a native <button>, and a <button> inside an <a> is invalid HTML.
 */

"use client";

import { CircleArrowRight02Icon } from "@icons";
import { useRouter } from "next/navigation";
import type { ComponentProps, MouseEventHandler, ReactNode } from "react";
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
  onClick,
  type,
  ...props
}: OnboardingCTAButtonProps) {
  const router = useRouter();
  const mergedClassName = cn("text-black!", className);
  const content = (
    <>
      {children}
      {!hideEndIcon &&
        (endContent ?? <CircleArrowRight02Icon className="size-4" />)}
    </>
  );

  // `href` navigates via the router rather than wrapping the button in a
  // <Link>: RaisedButton always renders a native <button>, and nesting a
  // <button> inside an <a> is invalid HTML. A caller's onClick can still
  // cancel navigation with event.preventDefault().
  const handleClick: MouseEventHandler<HTMLButtonElement> = (event) => {
    onClick?.(event);
    if (href && !event.defaultPrevented) {
      router.push(href);
    }
  };

  return (
    <RaisedButton
      color={color}
      className={mergedClassName}
      type={href ? "button" : type}
      onClick={handleClick}
      {...props}
    >
      {content}
    </RaisedButton>
  );
}
