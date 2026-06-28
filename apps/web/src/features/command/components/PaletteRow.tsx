"use client";

import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { AiMagicIcon, ArrowLeft02Icon, ArrowRight02Icon } from "@icons";
import { Command } from "cmdk";
import { COMMAND_MENU_STYLES as S } from "../model/config";
import type { Row } from "../model/paletteModel";
import type { CommandDot } from "../model/types";

// Hover (mouse) and selected (keyboard) are visually distinct.
const ROW =
  "mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm text-zinc-400 transition-colors hover:bg-zinc-800/40 aria-selected:bg-zinc-700/60 aria-selected:text-zinc-100!";

const DOT_COLOR: Record<CommandDot["color"], string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-500",
  blue: "bg-sky-500",
};

function StatusDot({ dot }: { dot: CommandDot }) {
  return (
    <Tooltip content={dot.label} size="sm" delay={250} closeDelay={0}>
      <span
        role="img"
        aria-label={dot.label}
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_COLOR[dot.color]}`}
      />
    </Tooltip>
  );
}

export function PaletteRow({
  row,
  number,
  onActivate,
  onSecondary,
}: {
  row: Row;
  number?: number;
  onActivate: () => void;
  onSecondary: () => void;
}) {
  if (row.kind === "ask") {
    return (
      <Command.Item value={row.id} onSelect={onActivate} className={ROW}>
        <AiMagicIcon width={18} height={18} className="text-primary" />
        <span className={`${S.flexOne} text-zinc-300`}>
          Ask GAIA{row.query ? `: "${row.query}"` : ""}
        </span>
      </Command.Item>
    );
  }

  if (row.kind === "back") {
    return (
      <Command.Item
        value={row.id}
        onSelect={onActivate}
        className={`${ROW} text-zinc-400!`}
      >
        <ArrowLeft02Icon width={18} height={18} />
        <span className={S.flexOne}>Go back</span>
      </Command.Item>
    );
  }

  if (row.kind === "action") {
    const { action } = row;
    return (
      <Command.Item
        value={row.id}
        onSelect={onActivate}
        className={`${ROW} ${action.destructive ? "text-red-400!" : ""}`}
      >
        {action.icon}
        <span className={S.flexOne}>{action.label}</span>
        {number !== undefined && <Kbd>{number}</Kbd>}
      </Command.Item>
    );
  }

  if (row.kind === "nav") {
    return (
      <Command.Item value={row.id} onSelect={onActivate} className={ROW}>
        {row.icon}
        <span className={S.flexOne}>{row.label}</span>
      </Command.Item>
    );
  }

  const isCategory = row.kind === "category";
  const icon = isCategory ? (
    <span className={row.group.accent}>{row.group.icon}</span>
  ) : (
    row.item.icon
  );
  const title = isCategory ? row.group.heading : row.item.title;
  const subtitle = isCategory
    ? `${row.group.items.length} ${row.group.items.length === 1 ? "item" : "items"}`
    : row.item.subtitle;
  const dot = isCategory ? undefined : row.item.dot;
  const accessory = isCategory ? undefined : row.item.accessory;
  const tint = isCategory ? undefined : row.item.tint;
  const drillable = isCategory || row.canDrill;

  return (
    <Command.Item value={row.id} onSelect={onActivate} className={ROW}>
      {icon}
      <div className={S.contentWrapper}>
        <div className="flex items-center gap-2">
          <span className={`truncate text-sm ${tint ?? ""}`}>{title}</span>
          {dot && <StatusDot dot={dot} />}
        </div>
        {subtitle && <div className={S.resultSubtitle}>{subtitle}</div>}
      </div>
      {accessory}
      {number !== undefined && <Kbd>{number}</Kbd>}
      {drillable && (
        <button
          type="button"
          aria-label="Open actions"
          onClick={(event) => {
            event.stopPropagation();
            onSecondary();
          }}
          className="shrink-0 rounded-md p-0.5 text-zinc-600 transition-colors hover:text-zinc-300"
        >
          <ArrowRight02Icon className="h-4 w-4" />
        </button>
      )}
    </Command.Item>
  );
}
