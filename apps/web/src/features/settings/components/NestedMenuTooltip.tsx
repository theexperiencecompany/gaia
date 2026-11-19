"use client";

import type {
  ComponentType,
  CSSProperties,
  ReactElement,
  ReactNode,
  SVGProps,
} from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GaiaButton } from "@/components/shared/GaiaButton";

// Position the flyout before the browser paints so the entrance animation
// never starts at the unclamped rect and then jumps.
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

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
  side: "left" | "right";
  originY: number;
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

  useIsomorphicLayoutEffect(() => {
    if (!isOpen || !itemRef) return;

    const updatePosition = () => {
      const panel = panelRef.current;
      if (!panel) return;

      const anchor = itemRef.getBoundingClientRect();
      // Layout box, not getBoundingClientRect: the entrance animation scales
      // the panel, and a transformed rect would under-measure its height.
      const width = panel.offsetWidth;
      const height = panel.offsetHeight;

      let side: "left" | "right" = "right";
      let left = anchor.right + GAP_PX;
      if (left + width > window.innerWidth - VIEWPORT_PADDING_PX) {
        side = "left";
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

      // Scale from the hovered row even when the panel is clamped away from
      // it, so the flyout still reads as growing out of that item.
      const originY = Math.min(
        Math.max(anchor.top + anchor.height / 2 - top, 0),
        height,
      );

      setPosition((previous) =>
        previous?.anchor === itemRef &&
        previous.top === top &&
        previous.left === left &&
        previous.side === side &&
        previous.originY === originY
          ? previous
          : { top, left, side, originY, anchor: itemRef },
      );
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
  // frame; the layout effect above steps in to flip or clamp before paint.
  const anchorRect = itemRef.getBoundingClientRect();
  const current =
    position?.anchor === itemRef
      ? position
      : {
          top: anchorRect.top,
          left: anchorRect.right + GAP_PX,
          side: "right" as const,
          originY: 0,
        };

  // React Aria marks everything outside the dropdown's focus scope inert, so
  // a body-level portal would be visible but unclickable. Mount beside the
  // popover inside its own overlay container instead.
  const portalContainer =
    itemRef.closest('[data-slot="dropdown-popover"]')?.parentElement ??
    document.body;

  return createPortal(
    <div
      ref={panelRef}
      data-side={current.side}
      style={
        {
          top: current.top,
          left: current.left,
          maxHeight: "calc(100vh - 16px)",
          maxWidth: "calc(100vw - 16px)",
          overflowY: "auto",
          overflowX: "hidden",
          overscrollBehavior: "contain",
          "--gaia-flyout-origin-y": `${current.originY}px`,
        } as CSSProperties
      }
      className="gaia-flyout fixed z-[100001] min-w-[160px] rounded-xl bg-secondary-bg shadow-xl"
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
