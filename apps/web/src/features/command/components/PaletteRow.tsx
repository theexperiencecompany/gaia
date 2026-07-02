"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { AiMagicIcon, ArrowLeft02Icon, ArrowRight02Icon } from "@icons";
import { Command } from "cmdk";
import { COMMAND_MENU_STYLES as S } from "../model/config";
import type { Row } from "../model/paletteModel";
import type { CommandDot } from "../model/types";

// Hover (mouse) and selected (keyboard) are visually distinct, but both kept
// subtle — a light white overlay rather than a raised zinc fill.
const ROW =
  "mx-2 flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2.5 text-sm text-zinc-400 transition-colors hover:bg-white/5 aria-selected:bg-white/10 aria-selected:text-zinc-100!";

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
  const subtitle = isCategory ? undefined : row.item.subtitle;
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
        <div // NOSONAR S6848: propagation guard so the drill Button below doesn't also activate the row
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Open actions"
            onPress={onSecondary}
            className="h-auto w-auto min-w-0 shrink-0 rounded-md p-0.5 text-zinc-600 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
          >
            <ArrowRight02Icon className="h-4 w-4" />
          </Button>
        </div>
      )}
    </Command.Item>
  );
}
