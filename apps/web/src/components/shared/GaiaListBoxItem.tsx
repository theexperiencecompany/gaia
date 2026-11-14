"use client";

import { ListBox } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";

type GaiaListBoxItemProps = Omit<
  ComponentProps<typeof ListBox.Item>,
  "children" | "textValue"
> & {
  /** The item's label; rendered as v2's one-line title when no children are given. */
  textValue: string;
  /** Rich row content (icon, two-line label) in place of the text label. */
  children?: ReactNode;
};

/** ListBox.Item with v2's selected check (v3 draws none unless the item renders its ItemIndicator). */
export function GaiaListBoxItem({
  children,
  textValue,
  ...props
}: GaiaListBoxItemProps) {
  return (
    <ListBox.Item textValue={textValue} {...props}>
      {children ?? <span className="truncate">{textValue}</span>}
      <ListBox.ItemIndicator />
    </ListBox.Item>
  );
}
