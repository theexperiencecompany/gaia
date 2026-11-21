"use client";

import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import {
  Calendar03Icon,
  CalendarAdd01Icon,
  FlashIcon,
  InformationCircleIcon,
  RepeatIcon,
} from "@icons";
import Image from "next/image";
import type { ComponentType, ReactNode } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  WORKFLOW_ICON_BG_ALPHA,
  WORKFLOW_ICON_MAP,
} from "@/features/workflows/constants/workflowIconCatalog";
import { cn } from "@/lib/utils";
import type { Task, WhenKind } from "./taskModel";

type IconComponent = ComponentType<{ className?: string; size?: number }>;

export const WHEN_ICONS: Record<WhenKind, IconComponent> = {
  anytime: CalendarAdd01Icon,
  at: Calendar03Icon,
  schedule: RepeatIcon,
  event: FlashIcon,
};

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
        className={cn(TILE, "bg-primary/15")}
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

export function AppIcon({ id, size = 16 }: { id: string; size?: number }) {
  return (
    <span className="flex shrink-0 items-center justify-center">
      {getToolCategoryIcon(id, {
        size,
        width: size,
        height: size,
        showBackground: false,
      })}
    </span>
  );
}

export function IntegrationStack({
  ids,
  size = 16,
  className,
}: {
  ids: string[];
  size?: number;
  className?: string;
}) {
  if (ids.length === 0) return null;
  return (
    <span className={cn("flex items-center gap-1.5", className)}>
      {ids.map((id) => (
        <AppIcon key={id} id={id} size={size} />
      ))}
    </span>
  );
}

export type ChipTone =
  | "default"
  | "danger"
  | "success"
  | "warning"
  | "info"
  | "primary";

/** DESIGN.md's status pairs: a /10 tint behind full-colour text. */
const CHIP_TONE: Record<ChipTone, string> = {
  default: "bg-zinc-800 text-zinc-300",
  danger: "bg-red-400/10 text-red-400",
  success: "bg-emerald-400/10 text-emerald-400",
  warning: "bg-amber-400/10 text-amber-400",
  info: "bg-blue-400/10 text-blue-400",
  primary: "bg-primary/10 text-primary",
};

/** A row's facts as small chips, the way the todo list has always shown due dates and checklists. */
export function MetaChip({
  icon,
  tone = "default",
  children,
}: {
  icon?: ReactNode;
  tone?: ChipTone;
  children: ReactNode;
}) {
  return (
    <Chip
      size="sm"
      radius="sm"
      variant="flat"
      startContent={icon}
      classNames={{
        base: cn("h-6 gap-1 px-1.5", CHIP_TONE[tone]),
        content: "px-0.5 text-xs font-medium tabular-nums",
      }}
    >
      {children}
    </Chip>
  );
}

/** A fact about the task: its name on the left, its value on the right. */
export function PropertyRow({
  label,
  hint,
  children,
}: {
  label: string;
  /** What the property does, behind an info icon beside its name. */
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-9 grid-cols-[6.5rem_1fr] items-center">
      <span className="flex items-center gap-1 text-[13px] text-zinc-500">
        {label}
        {hint && (
          <Tooltip
            content={hint}
            placement="top"
            delay={200}
            className="max-w-56"
          >
            <InformationCircleIcon
              aria-label={hint}
              className="size-3.5 text-zinc-600"
            />
          </Tooltip>
        )}
      </span>
      <div className="flex min-w-0 items-center">{children}</div>
    </div>
  );
}
