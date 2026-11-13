"use client";

import { Button, type ButtonProps } from "@heroui/react";

import {
  type ButtonHoverTone,
  type ButtonInset,
  type ButtonTone,
  type ButtonVariants,
  buttonOverlayVariants,
  buttonVariants,
} from "./buttonVariants";
import type { Shape } from "./shape";

/** HeroUI's button variants plus GAIA's, closed: a misspelt or v2 variant is a type error. */
export type GaiaButtonVariant = NonNullable<ButtonVariants["variant"]>;

type GaiaOnlyVariant =
  | "default-solid"
  | "default-soft"
  | "accent-soft"
  | "success-soft"
  | "warning-soft"
  | "text";

function isGaiaVariant(variant: GaiaButtonVariant): variant is GaiaOnlyVariant {
  return (
    variant === "default-solid" ||
    variant === "default-soft" ||
    variant === "accent-soft" ||
    variant === "success-soft" ||
    variant === "warning-soft" ||
    variant === "text"
  );
}

type GaiaButtonProps = Omit<ButtonProps, "variant" | "className"> & {
  variant?: GaiaButtonVariant;
  shape?: Shape;
  tone?: ButtonTone;
  hoverTone?: ButtonHoverTone;
  inset?: ButtonInset;
  className?: string;
};

/** HeroUI's Button with GAIA's extra variants and shape; HeroUI's own variants pass straight through. */
export function GaiaButton({
  variant = "primary",
  shape = "default",
  tone = "default",
  hoverTone = "none",
  inset = "default",
  size,
  isIconOnly,
  fullWidth,
  className,
  ...props
}: GaiaButtonProps) {
  if (!isGaiaVariant(variant)) {
    return (
      <Button
        variant={variant}
        size={size}
        isIconOnly={isIconOnly}
        fullWidth={fullWidth}
        className={buttonOverlayVariants({
          shape,
          tone,
          hoverTone,
          inset,
          className,
        })}
        {...props}
      />
    );
  }
  return (
    <Button
      variant="ghost"
      size={size}
      isIconOnly={isIconOnly}
      fullWidth={fullWidth}
      className={buttonVariants({
        variant,
        shape,
        tone,
        hoverTone,
        inset,
        size,
        isIconOnly,
        fullWidth,
        className,
      })}
      {...props}
    />
  );
}
