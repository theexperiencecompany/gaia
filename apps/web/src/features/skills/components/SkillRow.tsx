"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import { Delete02Icon, Link04Icon, PencilEdit02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Skill, SkillTarget } from "../api/types";
import { EXECUTOR_TARGET } from "../constants";
import { SkillTargetIcon } from "./SkillTargetIcon";

interface SkillRowProps {
  skill: Skill;
  /** Resolved metadata for the skill's target, if known. */
  targetMeta?: SkillTarget;
  /** Show the target chip inline (used in flat/search views, hidden in groups). */
  showTarget?: boolean;
  isDeleting?: boolean;
  onView: (skill: Skill) => void;
  onEdit: (skill: Skill) => void;
  onToggle: (skill: Skill, enabled: boolean) => void;
  onDelete: (skill: Skill) => void;
}

export function SkillRow({
  skill,
  targetMeta,
  showTarget = false,
  isDeleting = false,
  onView,
  onEdit,
  onToggle,
  onDelete,
}: Readonly<SkillRowProps>) {
  const isScoped = skill.target !== EXECUTOR_TARGET;

  return (
    <div className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-white/5">
      <button
        type="button"
        onClick={() => onView(skill)}
        className="min-w-0 flex-1 cursor-pointer text-left"
      >
        <div className="flex items-center gap-2">
          <p className="truncate text-sm text-zinc-100">{skill.name}</p>
          {showTarget && isScoped && targetMeta && (
            <Chip
              size="sm"
              variant="flat"
              startContent={
                <SkillTargetIcon
                  value={targetMeta.value}
                  icon={targetMeta.icon}
                  size={12}
                />
              }
              classNames={{
                base: "h-5 shrink-0 gap-1 bg-zinc-800 pl-1.5",
                content: "px-1 text-xs text-zinc-400",
              }}
            >
              {targetMeta.label}
            </Chip>
          )}
        </div>
        {skill.description && (
          <p className="mt-0.5 line-clamp-2 text-xs text-zinc-400">
            {skill.description}
          </p>
        )}
      </button>

      {skill.source_url &&
        (skill.source === "github" || skill.source === "url") && (
          <Chip
            as="a"
            href={skill.source_url}
            target="_blank"
            rel="noopener noreferrer"
            size="sm"
            variant="flat"
            startContent={
              skill.source === "github" ? (
                getToolCategoryIcon("github", {
                  size: 14,
                  width: 14,
                  height: 14,
                  showBackground: false,
                })
              ) : (
                <Link04Icon className="size-3.5 text-zinc-300" />
              )
            }
            classNames={{
              base: "h-6 shrink-0 cursor-pointer gap-1 bg-zinc-800 pl-2 data-[hover=true]:bg-zinc-700",
              content: "px-1 text-xs text-zinc-400",
            }}
          >
            {skill.source === "github" ? "GitHub" : "Source"}
          </Chip>
        )}

      <div className="flex shrink-0 items-center gap-1">
        <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label={`Edit ${skill.name}`}
            onPress={() => onEdit(skill)}
          >
            <PencilEdit02Icon className="size-4 text-zinc-400" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            color="danger"
            aria-label={`Delete ${skill.name}`}
            isLoading={isDeleting}
            onPress={() => onDelete(skill)}
          >
            <Delete02Icon className="size-4" />
          </Button>
        </div>
        <Switch
          size="sm"
          isSelected={skill.enabled}
          onValueChange={(enabled) => onToggle(skill, enabled)}
          aria-label={`${skill.enabled ? "Disable" : "Enable"} ${skill.name}`}
        />
      </div>
    </div>
  );
}
