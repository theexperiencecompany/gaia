import NextLink from "next/link";
import type { ComponentProps } from "react";

import { type ButtonVariants, buttonVariants } from "./buttonVariants";

type LinkButtonProps = Omit<ComponentProps<typeof NextLink>, "className"> &
  ButtonVariants & { className?: string };

/** A link styled as a HeroUI button: HeroUI's documented routing pattern, button variants on a Next.js link. */
export function LinkButton({
  variant,
  size,
  isIconOnly,
  fullWidth,
  className,
  ...linkProps
}: LinkButtonProps) {
  return (
    <NextLink
      className={buttonVariants({
        variant,
        size,
        isIconOnly,
        fullWidth,
        className,
      })}
      {...linkProps}
    />
  );
}
