"use client";

import { Label, ListBox, Select } from "@heroui/react";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
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
      <Select.Trigger>
        {selected && (
          <SkillTargetIcon
            value={selected.value}
            icon={selected.icon}
            size={16}
          />
        )}
        <GaiaSelectValue />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {targets.map((t) => (
            <GaiaListBoxItem key={t.value} id={t.value} textValue={t.label}>
              <SkillTargetIcon value={t.value} icon={t.icon} size={16} />
              {t.label}
            </GaiaListBoxItem>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
