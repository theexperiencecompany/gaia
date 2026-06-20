"use client";

import { Select, SelectItem } from "@heroui/select";
import type { SkillTarget } from "../api/types";
import { SkillTargetIcon } from "./SkillTargetIcon";

interface SkillTargetSelectProps {
  targets: SkillTarget[];
  value: string;
  onChange: (value: string) => void;
}

/** "Runs in" picker — executor + the user's connected integration subagents. */
export function SkillTargetSelect({
  targets,
  value,
  onChange,
}: SkillTargetSelectProps) {
  return (
    <Select
      label="Runs in"
      selectedKeys={[value]}
      onChange={(e) => e.target.value && onChange(e.target.value)}
      classNames={{ trigger: "rounded-xl bg-zinc-800" }}
      renderValue={(items) => {
        const selected = items[0]?.key as string | undefined;
        const meta = targets.find((t) => t.value === selected);
        if (!meta) return null;
        return (
          <div className="flex items-center gap-2">
            <SkillTargetIcon value={meta.value} icon={meta.icon} size={16} />
            <span>{meta.label}</span>
          </div>
        );
      }}
    >
      {targets.map((t) => (
        <SelectItem
          key={t.value}
          startContent={
            <SkillTargetIcon value={t.value} icon={t.icon} size={16} />
          }
        >
          {t.label}
        </SelectItem>
      ))}
    </Select>
  );
}
