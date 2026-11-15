"use client";

import { Select } from "@heroui/react";
import type { ComponentProps } from "react";

type GaiaSelectValueProps = ComponentProps<typeof Select.Value>;

/** Select.Value showing the selected item's textValue, as v2's trigger did; v3 renders the item's full content. */
export function GaiaSelectValue({
  children = ({ isPlaceholder, defaultChildren, selectedText }) =>
    isPlaceholder ? defaultChildren : selectedText,
  ...props
}: GaiaSelectValueProps) {
  return <Select.Value {...props}>{children}</Select.Value>;
}
