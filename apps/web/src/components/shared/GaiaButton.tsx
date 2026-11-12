"use client";

import { Button, type ButtonProps } from "@heroui/react";

import { type ButtonVariants, buttonVariants } from "./buttonVariants";

type GaiaVariant = Extract<
  ButtonVariants["variant"],
  "default-solid" | "accent-soft"
>;

type GaiaButtonProps = Omit<ButtonProps, "variant" | "className"> & {
  variant: GaiaVariant;
  className?: string;
};

/** HeroUI's Button in one of GAIA's two extra variants; every other variant is HeroUI's own Button. */
export function GaiaButton({
  variant,
  size,
  isIconOnly,
  fullWidth,
  className,
  ...props
}: GaiaButtonProps) {
  return (
    <Button
      variant="ghost"
      size={size}
      isIconOnly={isIconOnly}
      fullWidth={fullWidth}
      className={buttonVariants({
        variant,
        size,
        isIconOnly,
        fullWidth,
        className,
      })}
      {...props}
    />
  );
}
