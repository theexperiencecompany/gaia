"use client";

import { Chip, Tooltip } from "@heroui/react";
import {
  Calendar03Icon,
  CalendarAdd01Icon,
  FlashIcon,
  InformationCircleIcon,
  RepeatIcon,
} from "@icons";
import Image from "next/image";
import type { ComponentType, ReactNode } from "react";

import { chipVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { WORKFLOW_ICON_MAP } from "@/features/workflows/constants/workflowIconCatalog";
import { WORKFLOW_ICON_BG_ALPHA } from "@/features/workflows/constants/workflowIconStyle";
import { cn } from "@/lib/utils";
import type { Task, TaskWhen, WhenKind } from "./taskModel";

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
}: {
  ids: string[];
  size?: number;
}) {
  if (ids.length === 0) return null;
  return (
    <span className="flex items-center gap-1.5">
      {ids.map((id) => (
        <AppIcon key={id} id={id} size={size} />
      ))}
    </span>
  );
}

export type ChipTone = "default" | "danger" | "success" | "warning" | "info";

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
      className={chipVariants({
        status: tone,
        inset: "compact",
        className: shapeVariants({ shape: "sm", className: "h-6" }),
      })}
    >
      {icon}
      <Chip.Label className="text-xs leading-4 font-medium tabular-nums">
        {children}
      </Chip.Label>
    </Chip>
  );
}

/**
 * When a task is due or runs, always as one chip. Colour is kept for the two that
 * need you today; an event trigger leads with the app that fires it.
 */
export function WhenChip({ when }: { when: TaskWhen }) {
  if (!when.label) return null;
  const Icon = WHEN_ICONS[when.kind];
  const tone: ChipTone = when.overdue
    ? "danger"
    : when.isToday
      ? "success"
      : when.kind === "schedule"
        ? "info"
        : "default";

  return (
    <MetaChip
      tone={tone}
      icon={
        when.app ? (
          <AppIcon id={when.app} size={14} />
        ) : (
          <Icon className="size-3.5" />
        )
      }
    >
      {when.overdue ? `Overdue, ${when.label}` : when.label}
    </MetaChip>
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
          <Tooltip delay={200}>
            <Tooltip.Trigger
              aria-label={hint}
              render={(props) => <span {...props} className="flex" />}
            >
              <InformationCircleIcon className="size-3.5 text-zinc-600" />
            </Tooltip.Trigger>
            <Tooltip.Content placement="top" className="max-w-56">
              {hint}
            </Tooltip.Content>
          </Tooltip>
        )}
      </span>
      <div className="flex min-w-0 items-center">{children}</div>
    </div>
  );
}
