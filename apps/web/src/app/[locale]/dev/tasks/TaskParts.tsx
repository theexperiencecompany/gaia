"use client";

import Image from "next/image";

import { WORKFLOW_ICON_MAP } from "@/features/workflows/constants/workflowIconCatalog";
import { WORKFLOW_ICON_BG_ALPHA } from "@/features/workflows/constants/workflowIconStyle";
import { cn } from "@/lib/utils";
import type { Task } from "./taskModel";

export function GaiaMark({ size = 20 }: { size?: number }) {
  return (
    <Image
      src="/brand/gaia_logo.svg"
      alt="GAIA"
      width={size}
      height={size}
      className="shrink-0 select-none"
      draggable={false}
    />
  );
}

const TILE =
  "flex shrink-0 translate-y-0.5 items-center justify-center rounded-lg";

/**
 * The square every GAIA task leads with: its own icon on a 15% tint of its colour,
 * or the GAIA mark on a tint of the brand colour when it has none.
 */
export function TaskIconTile({
  icon,
  size = 28,
}: {
  icon?: Task["icon"];
  size?: number;
}) {
  const def = icon ? WORKFLOW_ICON_MAP.get(icon.name) : undefined;
  if (!icon || !def) {
    return (
      <span
        className={cn(TILE, "bg-accent/15")}
        style={{ width: size, height: size }}
      >
        <GaiaMark size={Math.round(size * 0.57)} />
      </span>
    );
  }
  return (
    <span
      className={TILE}
      style={{
        width: size,
        height: size,
        backgroundColor: `${icon.color}${WORKFLOW_ICON_BG_ALPHA}`,
      }}
    >
      <def.Icon size={Math.round(size * 0.57)} style={{ color: icon.color }} />
    </span>
  );
}
