"use client";

import type { ComponentType, ReactElement, ReactNode, SVGProps } from "react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface MenuItem {
  iconElement?: ReactElement;
  key: string;
  label: string;
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
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

const GAP_PX = 8;
const VIEWPORT_PADDING_PX = 8;

interface FlyoutPosition {
  top: number;
  left: number;
  anchor: HTMLElement;
}

export function NestedMenuTooltip({
  isOpen,
  onOpenChange,
  itemRef,
  menuItems,
  iconClasses = "w-[18px] h-[18px]",
  customContent,
}: NestedMenuTooltipProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<FlyoutPosition | null>(null);

  useEffect(() => {
    if (!isOpen || !itemRef) return;

    const updatePosition = () => {
      const panel = panelRef.current;
      if (!panel) return;

      const anchor = itemRef.getBoundingClientRect();
      const { width, height } = panel.getBoundingClientRect();

      let left = anchor.right + GAP_PX;
      if (left + width > window.innerWidth - VIEWPORT_PADDING_PX) {
        left = anchor.left - width - GAP_PX;
      }
      left = Math.max(
        VIEWPORT_PADDING_PX,
        Math.min(left, window.innerWidth - width - VIEWPORT_PADDING_PX),
      );

      let top = anchor.top;
      if (top + height > window.innerHeight - VIEWPORT_PADDING_PX) {
        top = window.innerHeight - height - VIEWPORT_PADDING_PX;
      }
      top = Math.max(VIEWPORT_PADDING_PX, top);

      setPosition({ top, left, anchor: itemRef });
    };

    updatePosition();

    // The What's-new flyout grows when its releases arrive, so re-measure on
    // any size change, not just when the anchor moves.
    const resizeObserver = new ResizeObserver(updatePosition);
    if (panelRef.current) resizeObserver.observe(panelRef.current);

    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [isOpen, itemRef]);

  if (!isOpen || !itemRef || typeof document === "undefined") return null;

  // The anchor's live rect keeps the flyout attached from the first painted
  // frame; the effect above only steps in to flip or clamp near an edge.
  const anchorRect = itemRef.getBoundingClientRect();
  const current =
    position?.anchor === itemRef
      ? position
      : { top: anchorRect.top, left: anchorRect.right + GAP_PX };

  // React Aria marks everything outside the dropdown's focus scope inert, so
  // a body-level portal would be visible but unclickable. Mount beside the
  // popover inside its own overlay container instead.
  const portalContainer =
    itemRef.closest('[data-slot="dropdown-popover"]')?.parentElement ??
    document.body;

  return createPortal(
    <div
      ref={panelRef}
      style={{ top: current.top, left: current.left }}
      className="fixed z-[100001] min-w-[160px] rounded-xl bg-secondary-bg shadow-xl"
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
              <GaiaButton
                key={item.key}
                variant="ghost"
                size="sm"
                tone="muted"
                hoverTone="white"
                className="justify-start text-sm transition"
                onPress={() => {
                  item.action();
                  onOpenChange(false);
                }}
              >
                {iconContent}
                {item.label}
                {item.badge}
              </GaiaButton>
            );
          })}
        </div>
      )}
    </div>,
    portalContainer,
  );
}
