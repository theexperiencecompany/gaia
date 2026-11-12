"use client";

import { Label, ListBox, Select } from "@heroui/react";
import { fieldVariants } from "@/components/shared/fieldVariants";
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
}: Readonly<SkillTargetSelectProps>) {
  const selected = targets.find((t) => t.value === value);

  return (
    <Select
      className={fieldVariants({ labelPlacement: "inside" })}
      value={value}
      onChange={(key) => key != null && onChange(String(key))}
    >
      <Label>Runs in</Label>
      <Select.Trigger className="rounded-xl bg-zinc-800">
        {selected && (
          <SkillTargetIcon
            value={selected.value}
            icon={selected.icon}
            size={16}
          />
        )}
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {targets.map((t) => (
            <ListBox.Item key={t.value} id={t.value} textValue={t.label}>
              <SkillTargetIcon value={t.value} icon={t.icon} size={16} />
              {t.label}
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
