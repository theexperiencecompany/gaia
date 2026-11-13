"use client";

import { SearchField, Tabs } from "@heroui/react";
import {
  FolderLibraryIcon,
  PlusSignIcon,
  PuzzleIcon,
  Search01Icon,
} from "@icons";
import type { ComponentType } from "react";
import { useEffect, useMemo, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  inputVariants,
  tabsVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { useConfirmation } from "@/hooks/useConfirmation";
import { track } from "@/lib/analytics";
import type { Skill } from "../api/types";
import { useSkills } from "../hooks/useSkills";
import { buildTargetMap } from "../utils";
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

  const targetByValue = useMemo(() => buildTargetMap(targets), [targets]);

  // Debounce so a search event fires per pause, not per keystroke.
  useEffect(() => {
    if (!query.trim()) return;
    const timer = setTimeout(() => {
      track("skill:searched", {});
    }, 500);
    return () => clearTimeout(timer);
  }, [query]);

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
          className={tabsVariants({
            color: "accent",
            className: shapeVariants({ shape: "pill", className: "shrink-0" }),
          })}
          variant="primary"
          selectedKey={tab}
          onSelectionChange={(key) => setTab(key as string)}
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label="Skills">
              <Tabs.Tab id="yours">
                <TabTitle icon={PuzzleIcon} label="Your Skills" />
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="builtin">
                <TabTitle icon={FolderLibraryIcon} label="Built-in" />
                <Tabs.Indicator />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
        <div className="flex-1" />
        <SearchField
          aria-label="Search skills"
          value={query}
          onChange={setQuery}
          className={inputVariants({ size: "sm", className: "max-w-56" })}
        >
          <SearchField.Group>
            <SearchField.SearchIcon>
              <Search01Icon className="size-4 text-zinc-500" />
            </SearchField.SearchIcon>
            <SearchField.Input placeholder="Search skills" />
            <SearchField.ClearButton />
          </SearchField.Group>
        </SearchField>
        <GaiaButton
          size="sm"
          className="shrink-0 rounded-xl"
          onPress={openCreate}
          variant="primary"
        >
          <PlusSignIcon className="size-4" />
          New skill
        </GaiaButton>
      </div>

      <div className="min-h-0 flex-1">
        {tab === "yours" ? (
          <SkillsList
            skills={skills}
            targetByValue={targetByValue}
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

interface TabTitleProps {
  icon: ComponentType<{ className?: string }>;
  label: string;
}

function TabTitle({ icon: Icon, label }: Readonly<TabTitleProps>) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-4" />
      <span>{label}</span>
    </div>
  );
}
