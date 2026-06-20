"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Tab, Tabs } from "@heroui/tabs";
import {
  FolderLibraryIcon,
  PlusSignIcon,
  PuzzleIcon,
  Search01Icon,
} from "@icons";
import type { ComponentType } from "react";
import { useMemo, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useConfirmation } from "@/hooks/useConfirmation";
import type { Skill, SkillTarget } from "../api/types";
import { useSkills } from "../hooks/useSkills";
import { BuiltinSkillsList } from "./BuiltinSkillsList";
import { SkillEditorModal } from "./SkillEditorModal";
import type { SkillPreview } from "./SkillPreviewModal";
import { SkillPreviewModal } from "./SkillPreviewModal";
import { SkillsList } from "./SkillsList";

export default function SkillsManagement() {
  const { skills, targets, loading, refetch, setEnabled, removeSkill } =
    useSkills();
  const [tab, setTab] = useState("yours");
  const [query, setQuery] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [previewSkill, setPreviewSkill] = useState<SkillPreview | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const { confirm, confirmationProps } = useConfirmation();

  const targetByValue = useMemo(() => {
    const map = new Map<string, SkillTarget>();
    for (const t of targets) map.set(t.value, t);
    return map;
  }, [targets]);

  const openCreate = () => {
    setEditingSkill(null);
    setEditorOpen(true);
  };
  const openEdit = (skill: Skill) => {
    setEditingSkill(skill);
    setEditorOpen(true);
  };
  const openView = (skill: Skill) => {
    const meta = targetByValue.get(skill.target);
    setPreviewSkill({
      name: skill.name,
      description: skill.description,
      body: skill.body_content ?? "",
      groupLabel: meta?.label ?? skill.target,
      icon: meta?.icon ?? skill.target,
    });
  };

  const handleDelete = async (skill: Skill) => {
    const confirmed = await confirm({
      title: `Delete "${skill.name}"?`,
      message:
        "This permanently removes the skill and its files. This can't be undone.",
      confirmText: "Delete",
      cancelText: "Cancel",
      variant: "destructive",
    });
    if (!confirmed) return;
    setDeletingId(skill.id);
    await removeSkill(skill);
    setDeletingId(null);
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div>
        <h2 className="text-xl font-medium text-white">Skills</h2>
        <p className="mt-1 text-sm text-zinc-400">
          Reusable workflows your assistant can follow, scoped to where they
          run.
        </p>
      </div>

      {/* Tabs, search, and New skill share one row. */}
      <div className="flex items-center gap-3">
        <Tabs
          variant="solid"
          color="primary"
          radius="full"
          selectedKey={tab}
          onSelectionChange={(key) => setTab(key as string)}
        >
          <Tab
            key="yours"
            title={<TabTitle icon={PuzzleIcon} label="Your Skills" />}
          />
          <Tab
            key="builtin"
            title={<TabTitle icon={FolderLibraryIcon} label="Built-in" />}
          />
        </Tabs>
        <div className="flex-1" />
        <Input
          size="sm"
          variant="flat"
          radius="lg"
          placeholder="Search skills"
          value={query}
          onValueChange={setQuery}
          startContent={<Search01Icon className="size-4 text-zinc-500" />}
          className="max-w-56"
          isClearable
          onClear={() => setQuery("")}
        />
        <Button
          size="sm"
          color="primary"
          className="shrink-0 rounded-xl"
          startContent={<PlusSignIcon className="size-4" />}
          onPress={openCreate}
        >
          New skill
        </Button>
      </div>

      <div className="min-h-0 flex-1">
        {tab === "yours" ? (
          <SkillsList
            skills={skills}
            targets={targets}
            loading={loading}
            query={query}
            deletingId={deletingId}
            onCreate={openCreate}
            onView={openView}
            onEdit={openEdit}
            onToggle={setEnabled}
            onDelete={handleDelete}
          />
        ) : (
          <BuiltinSkillsList query={query} />
        )}
      </div>

      <SkillEditorModal
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={() => {
          refetch();
          setTab("yours");
        }}
        targets={targets}
        skill={editingSkill}
      />
      <SkillPreviewModal
        skill={previewSkill}
        onClose={() => setPreviewSkill(null)}
      />
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
}

function TabTitle({
  icon: Icon,
  label,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-4" />
      <span>{label}</span>
    </div>
  );
}
