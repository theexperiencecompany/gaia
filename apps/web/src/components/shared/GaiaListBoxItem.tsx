"use client";

import { ListBox } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";

type GaiaListBoxItemProps = Omit<
  ComponentProps<typeof ListBox.Item>,
  "children"
> & {
  children: ReactNode;
};

/** ListBox.Item with v2's selected check; v3 draws none unless the item renders its ItemIndicator. */
export function GaiaListBoxItem({ children, ...props }: GaiaListBoxItemProps) {
  return (
    <ListBox.Item {...props}>
      {children}
      <ListBox.ItemIndicator />
    </ListBox.Item>
  );
}
