"use client";

import NextLink from "next/link";
import type { ComponentProps } from "react";
import { Focusable } from "react-aria-components";

import { buttonVariants } from "./buttonVariants";
import type { ButtonVariants } from "./buttonVariants.types";

type LinkButtonProps = Omit<ComponentProps<typeof NextLink>, "className"> &
  ButtonVariants & { className?: string };

/**
 * A link styled as a HeroUI button: HeroUI's documented routing pattern, button variants on a Next.js link.
 * Focusable hands the link React Aria's trigger props, so a Tooltip around it opens like one around a Button.
 */
export function LinkButton({
  variant,
  shape,
  tone,
  hoverTone,
  inset,
  elevation,
  size,
  isIconOnly,
  fullWidth,
  className,
  ...linkProps
}: LinkButtonProps) {
  return (
    <Focusable>
      <NextLink
        className={buttonVariants({
          variant,
          shape,
          tone,
          hoverTone,
          inset,
          elevation,
          size,
          isIconOnly,
          fullWidth,
          className,
        })}
        {...linkProps}
      />
    </Focusable>
  );
}
