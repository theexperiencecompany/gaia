"use client";

import { Button, type ButtonProps } from "@heroui/react";

import { type ButtonVariants, buttonVariants } from "./buttonVariants";
import { type Shape, shapeVariants } from "./shape";

/** HeroUI's button variants plus GAIA's, closed: a misspelt or v2 variant is a type error. */
export type GaiaButtonVariant = NonNullable<ButtonVariants["variant"]>;

type GaiaOnlyVariant = "default-solid" | "default-soft" | "accent-soft";

function isGaiaVariant(variant: GaiaButtonVariant): variant is GaiaOnlyVariant {
  return (
    variant === "default-solid" ||
    variant === "default-soft" ||
    variant === "accent-soft"
  );
}

type GaiaButtonProps = Omit<ButtonProps, "variant" | "className"> & {
  variant?: GaiaButtonVariant;
  shape?: Shape;
  className?: string;
};

/** HeroUI's Button with GAIA's extra variants and shape; HeroUI's own variants pass straight through. */
export function GaiaButton({
  variant = "primary",
  shape = "default",
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
        className={shapeVariants({ shape, className })}
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
        size,
        isIconOnly,
        fullWidth,
        className,
      })}
      {...props}
    />
  );
}
