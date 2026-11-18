import type { VariantProps } from "tailwind-variants";

import type {
  BUTTON_ELEVATION_CLASSES,
  BUTTON_HOVER_TONE_CLASSES,
  BUTTON_INSET_CLASSES,
  buttonVariants,
} from "./buttonVariants";

export type ButtonHoverTone = keyof typeof BUTTON_HOVER_TONE_CLASSES;

export type ButtonInset = keyof typeof BUTTON_INSET_CLASSES;

export type ButtonElevation = keyof typeof BUTTON_ELEVATION_CLASSES;

export type ButtonVariants = VariantProps<typeof buttonVariants>;
