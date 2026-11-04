"use client";

import { Button, Tooltip } from "@heroui/react";
import type { ReactElement, ReactNode } from "react";

interface MenuItem {
  iconElement?: ReactElement;
  key: string;
  label: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  action: () => void;
  badge?: ReactElement;
}

interface NestedMenuTooltipProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  itemRef: HTMLElement | null;
  menuItems?: MenuItem[];
  iconClasses?: string;
  customContent?: ReactNode;
}

export function NestedMenuTooltip({
  isOpen,
  onOpenChange,
  itemRef,
  menuItems,
  iconClasses = "w-[18px] h-[18px]",
  customContent,
}: NestedMenuTooltipProps) {
  if (!itemRef) return null;

  const itemRect = itemRef.getBoundingClientRect();

  return (
    <Tooltip
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      delay={0}
      closeDelay={0}
    >
      <Tooltip.Trigger className="border-0">
        <div
          style={{
            position: "fixed",
            left: itemRect.right,
            top: itemRect.top,
            width: 1,
            height: 1,
            pointerEvents: "none",
          }}
        />
      </Tooltip.Trigger>
      <Tooltip.Content
        placement="right top"
        offset={8}
        className="border-0! bg-secondary-bg p-0 outline-0!"
      >
        <div
          onMouseEnter={() => onOpenChange(true)}
          onMouseLeave={() => onOpenChange(false)}
        >
          {customContent ?? (
            <div className="flex flex-col p-1">
              {menuItems?.map((item) => {
                const Icon = item.icon;
                const iconContent = item.iconElement ? (
                  item.iconElement
                ) : Icon ? (
                  <Icon className={iconClasses} />
                ) : null;

                return (
                  <Button
                    key={item.key}
                    variant="tertiary"
                    size="sm"
                    className="justify-start text-sm text-zinc-400 transition hover:text-white"
                    onPress={() => {
                      item.action();
                      onOpenChange(false);
                    }}
                  >
                    {iconContent}
                    {item.label}
                    {item.badge}
                  </Button>
                );
              })}
            </div>
          )}
        </div>
      </Tooltip.Content>
    </Tooltip>
  );
}
