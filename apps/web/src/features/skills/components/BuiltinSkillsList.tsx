"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import NextLink from "next/link";
import { useEffect, useMemo, useState } from "react";
import { skillsApi } from "../api/skillsApi";
import type { BuiltinSkillInfo } from "../api/types";
import { SkillGroup } from "./SkillGroup";
import { SkillPreviewModal } from "./SkillPreviewModal";
import { SkillTargetIcon } from "./SkillTargetIcon";

interface BuiltinSkillsListProps {
  query: string;
}

interface Group {
  label: string;
  icon: string;
  connected: boolean;
  skills: BuiltinSkillInfo[];
}

export function BuiltinSkillsList({ query }: BuiltinSkillsListProps) {
  const [skills, setSkills] = useState<BuiltinSkillInfo[] | null>(null);
  const [selected, setSelected] = useState<BuiltinSkillInfo | null>(null);

  useEffect(() => {
    let active = true;
    skillsApi
      .listBuiltinSkills()
      .then((res) => active && setSkills(res.skills))
      .catch(() => active && setSkills([]));
    return () => {
      active = false;
    };
  }, []);

  const groups = useMemo<Group[]>(() => {
    if (!skills) return [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? skills.filter(
          (s) =>
            s.name.toLowerCase().includes(q) ||
            s.description.toLowerCase().includes(q),
        )
      : skills;

    const byLabel = new Map<string, Group>();
    for (const skill of filtered) {
      const existing = byLabel.get(skill.group_label);
      if (existing) existing.skills.push(skill);
      else
        byLabel.set(skill.group_label, {
          label: skill.group_label,
          icon: skill.icon,
          connected: skill.connected,
          skills: [skill],
        });
    }
    // Connected groups first, then deactivated; alphabetical within each.
    return [...byLabel.values()].sort((a, b) => {
      if (a.connected !== b.connected) return a.connected ? -1 : 1;
      return a.label.localeCompare(b.label);
    });
  }, [skills, query]);

  if (skills === null) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {groups.length === 0 ? (
        <p className="py-8 text-center text-xs text-zinc-500">
          No built-in skills match your search.
        </p>
      ) : (
        groups.map((group) => (
          <SkillGroup
            // Key includes search state so toggling search remounts folders open/closed.
            key={`${group.label}${query.trim() ? "-q" : ""}`}
            icon={
              <SkillTargetIcon value={group.icon} icon={group.icon} size={20} />
            }
            label={group.label}
            count={group.skills.length}
            deactivated={!group.connected}
            defaultOpen={query.trim().length > 0}
            trailing={
              group.connected ? undefined : (
                <div className="flex shrink-0 items-center gap-2">
                  <Chip
                    size="sm"
                    variant="flat"
                    color="warning"
                    classNames={{
                      base: "bg-warning/15",
                      content: "text-xs font-medium",
                    }}
                  >
                    Not connected
                  </Chip>
                  <Button
                    as={NextLink}
                    href={`/integrations?id=${group.icon}`}
                    size="sm"
                    color="primary"
                    variant="flat"
                    className="rounded-lg"
                  >
                    Connect
                  </Button>
                </div>
              )
            }
          >
            {group.skills.map((skill) => (
              <button
                key={skill.slug}
                type="button"
                onClick={() => setSelected(skill)}
                className="flex w-full cursor-pointer flex-col px-4 py-3 text-left transition-colors hover:bg-white/5"
              >
                <span className="text-sm text-zinc-100">{skill.name}</span>
                {skill.description && (
                  <span className="mt-0.5 line-clamp-2 text-xs text-zinc-400">
                    {skill.description}
                  </span>
                )}
              </button>
            ))}
          </SkillGroup>
        ))
      )}

      <SkillPreviewModal
        skill={
          selected
            ? {
                name: selected.name,
                description: selected.description,
                body: selected.body,
                groupLabel: selected.group_label,
                icon: selected.icon,
                badge: "Built-in",
              }
            : null
        }
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
