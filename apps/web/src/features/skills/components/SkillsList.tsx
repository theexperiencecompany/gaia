"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { PlusSignIcon, PuzzleIcon } from "@icons";
import { useMemo } from "react";
import type { Skill, SkillTarget } from "../api/types";
import { EXECUTOR_TARGET } from "../constants";
import { SkillGroup } from "./SkillGroup";
import { SkillRow } from "./SkillRow";
import { SkillTargetIcon } from "./SkillTargetIcon";

interface SkillsListProps {
  skills: Skill[];
  targets: SkillTarget[];
  loading: boolean;
  query: string;
  deletingId: string | null;
  onCreate: () => void;
  onView: (skill: Skill) => void;
  onEdit: (skill: Skill) => void;
  onToggle: (skill: Skill, enabled: boolean) => void;
  onDelete: (skill: Skill) => void;
}

function matches(skill: Skill, query: string): boolean {
  const q = query.toLowerCase();
  return (
    skill.name.toLowerCase().includes(q) ||
    skill.description.toLowerCase().includes(q)
  );
}

export function SkillsList({
  skills,
  targets,
  loading,
  query,
  deletingId,
  onCreate,
  onView,
  onEdit,
  onToggle,
  onDelete,
}: SkillsListProps) {
  const targetByValue = useMemo(() => {
    const map = new Map<string, SkillTarget>();
    for (const t of targets) map.set(t.value, t);
    return map;
  }, [targets]);

  const isSearching = query.trim().length > 0;
  const visible = isSearching
    ? skills.filter((s) => matches(s, query))
    : skills;

  const active = visible.filter((s) => targetByValue.has(s.target));
  const inactive = visible.filter((s) => !targetByValue.has(s.target));

  const activeTargets = useMemo(() => {
    const present = [...new Set(active.map((s) => s.target))];
    return present.sort((a, b) => {
      if (a === EXECUTOR_TARGET) return -1;
      if (b === EXECUTOR_TARGET) return 1;
      const la = targetByValue.get(a)?.label ?? a;
      const lb = targetByValue.get(b)?.label ?? b;
      return la.localeCompare(lb);
    });
  }, [active, targetByValue]);

  // Folders only when scoping varies; a pure executor list stays flat.
  const grouped =
    !isSearching &&
    (activeTargets.length > 1 || activeTargets[0] !== EXECUTOR_TARGET);

  const row = (skill: Skill, showTarget: boolean) => (
    <SkillRow
      key={skill.id}
      skill={skill}
      targetMeta={targetByValue.get(skill.target)}
      showTarget={showTarget}
      isDeleting={deletingId === skill.id}
      onView={onView}
      onEdit={onEdit}
      onToggle={onToggle}
      onDelete={onDelete}
    />
  );

  if (loading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
      </div>
    );
  }

  if (visible.length === 0) {
    return <EmptyState searching={isSearching} onCreate={onCreate} />;
  }

  return (
    <div className="space-y-3">
      {grouped ? (
        activeTargets.map((targetValue) => {
          const meta = targetByValue.get(targetValue);
          const rows = active.filter((s) => s.target === targetValue);
          return (
            <SkillGroup
              key={targetValue}
              icon={
                meta ? (
                  <SkillTargetIcon
                    value={meta.value}
                    icon={meta.icon}
                    size={20}
                  />
                ) : (
                  <PuzzleIcon className="size-5 text-zinc-400" />
                )
              }
              label={meta?.label ?? targetValue}
              count={rows.length}
            >
              {rows.map((s) => row(s, false))}
            </SkillGroup>
          );
        })
      ) : (
        <div className="divide-y divide-zinc-800/60 overflow-hidden rounded-2xl bg-zinc-900/60">
          {active.map((s) => row(s, isSearching))}
        </div>
      )}

      {inactive.length > 0 && (
        <SkillGroup
          icon={<PuzzleIcon className="size-5 text-zinc-500" />}
          label="Inactive"
          count={inactive.length}
          deactivated
          defaultOpen={false}
        >
          {inactive.map((s) => row(s, true))}
        </SkillGroup>
      )}
    </div>
  );
}

function EmptyState({
  searching,
  onCreate,
}: {
  searching: boolean;
  onCreate: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl bg-zinc-900/60 px-6 py-14 text-center">
      <div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-zinc-800">
        <PuzzleIcon className="size-6 text-zinc-500" />
      </div>
      <p className="text-sm text-zinc-300">
        {searching ? "No skills match your search" : "No skills yet"}
      </p>
      {!searching && (
        <>
          <p className="mt-1 max-w-sm text-xs text-zinc-500">
            Skills are reusable workflows your assistant can follow — like
            triaging your inbox or planning your day.
          </p>
          <Button
            size="sm"
            color="primary"
            className="mt-4 rounded-xl"
            startContent={<PlusSignIcon className="size-4" />}
            onPress={onCreate}
          >
            New skill
          </Button>
        </>
      )}
    </div>
  );
}
