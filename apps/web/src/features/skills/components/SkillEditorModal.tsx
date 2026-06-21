"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import { Github01Icon } from "@icons";
import { useEffect, useMemo, useState } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { toast } from "@/lib/toast";
import { skillsApi } from "../api/skillsApi";
import type { Skill, SkillTarget } from "../api/types";
import {
  CONSECUTIVE_HYPHENS,
  EXECUTOR_TARGET,
  MAX_SKILL_DESCRIPTION_LENGTH,
  MAX_SKILL_NAME_LENGTH,
  SKILL_NAME_PATTERN,
} from "../constants";
import { SkillImportForm } from "./SkillImportForm";
import { SkillTargetSelect } from "./SkillTargetSelect";

interface SkillEditorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  targets: SkillTarget[];
  /** The skill being edited, or null when creating. */
  skill: Skill | null;
}

export function SkillEditorModal({
  isOpen,
  onClose,
  onSaved,
  targets,
  skill,
}: Readonly<SkillEditorModalProps>) {
  const isEdit = skill !== null;

  const [mode, setMode] = useState<"write" | "import">("write");
  const [instructionsTab, setInstructionsTab] = useState<"write" | "preview">(
    "write",
  );
  const [name, setName] = useState("");
  const [target, setTarget] = useState(EXECUTOR_TARGET);
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setMode("write");
    setInstructionsTab("write");
    setName(skill?.name ?? "");
    setTarget(skill?.target ?? EXECUTOR_TARGET);
    setDescription(skill?.description ?? "");
    setInstructions(skill?.body_content ?? "");
  }, [isOpen, skill]);

  const nameError = useMemo(() => {
    if (!name) return undefined;
    if (name.length > MAX_SKILL_NAME_LENGTH)
      return `Keep it under ${MAX_SKILL_NAME_LENGTH} characters`;
    if (!SKILL_NAME_PATTERN.test(name) || CONSECUTIVE_HYPHENS.test(name))
      return "Lowercase letters, numbers, and single hyphens only";
    return undefined;
  }, [name]);

  const descriptionError = useMemo(() => {
    if (description.length > MAX_SKILL_DESCRIPTION_LENGTH)
      return `Keep it under ${MAX_SKILL_DESCRIPTION_LENGTH} characters`;
    return undefined;
  }, [description]);

  // Name is immutable while editing, so its validity can't block a save
  // (legacy skills may predate stricter name rules).
  const nameValid = isEdit || (name.length > 0 && !nameError);
  const isValid =
    nameValid &&
    description.trim().length > 0 &&
    !descriptionError &&
    instructions.trim().length > 0;

  const handleSave = async () => {
    if (!isValid) return;
    setSaving(true);
    try {
      if (isEdit) {
        await skillsApi.updateSkill(skill.id, {
          description: description.trim(),
          instructions,
          target,
        });
        toast.success(`Saved "${name}"`);
      } else {
        await skillsApi.createSkill({
          name,
          description: description.trim(),
          instructions,
          target,
        });
        toast.success(`Created "${name}"`);
      }
      onSaved();
      onClose();
    } catch {
      // The API interceptor surfaces the server's error message.
    } finally {
      setSaving(false);
    }
  };

  const writeForm = (
    <div className="flex flex-col gap-4">
      <Input
        label="Name"
        placeholder="triage-inbox"
        value={name}
        onValueChange={setName}
        isDisabled={isEdit}
        description={
          isEdit
            ? "The name is the skill's identity and can't be changed."
            : "Lowercase, hyphenated. This is how the agent refers to it."
        }
        isInvalid={!!nameError}
        errorMessage={nameError}
      />
      <Input
        label="Description"
        placeholder="Sort, label, and draft replies for new mail"
        value={description}
        onValueChange={setDescription}
        description="What it does and when to use it — the agent sees this at all times."
        isInvalid={!!descriptionError}
        errorMessage={descriptionError}
      />
      <SkillTargetSelect
        targets={targets}
        value={target}
        onChange={setTarget}
      />
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-300">Instructions</span>
          <Tabs
            size="sm"
            radius="full"
            selectedKey={instructionsTab}
            onSelectionChange={(key) =>
              setInstructionsTab(key as "write" | "preview")
            }
          >
            <Tab key="write" title="Write" />
            <Tab key="preview" title="Preview" />
          </Tabs>
        </div>
        {instructionsTab === "write" ? (
          <Textarea
            aria-label="Instructions"
            placeholder={"# Triage inbox\n\n1. Fetch unread mail\n2. ..."}
            value={instructions}
            onValueChange={setInstructions}
            minRows={8}
            maxRows={18}
            classNames={{ input: "font-mono text-xs" }}
          />
        ) : (
          <div className="min-h-44 rounded-xl bg-zinc-900/60 p-4">
            {instructions.trim() ? (
              <MarkdownRenderer
                content={instructions}
                hideCodeToolbar
                className="prose-sm prose-p:text-zinc-300 prose-li:text-zinc-300"
              />
            ) : (
              <p className="text-xs text-zinc-500">Nothing to preview yet.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="2xl" scrollBehavior="inside">
      <ModalContent>
        <ModalHeader className="flex-col items-start gap-1">
          <span>{isEdit ? "Edit skill" : "New skill"}</span>
          <span className="text-xs font-normal text-zinc-500">
            {isEdit
              ? "Update what this skill does and where it runs."
              : "Teach your assistant a reusable workflow it can follow."}
          </span>
        </ModalHeader>
        <ModalBody>
          {isEdit ? (
            writeForm
          ) : (
            <Tabs
              radius="full"
              variant="solid"
              color="primary"
              selectedKey={mode}
              onSelectionChange={(key) => setMode(key as "write" | "import")}
              classNames={{ base: "mb-1" }}
            >
              <Tab key="write" title="Write your own">
                {writeForm}
              </Tab>
              <Tab
                key="import"
                title={
                  <div className="flex items-center gap-1.5">
                    <Github01Icon className="size-4" />
                    <span>Import from GitHub</span>
                  </div>
                }
              >
                <SkillImportForm targets={targets} onInstalled={onSaved} />
              </Tab>
            </Tabs>
          )}
        </ModalBody>
        <ModalFooter>
          <Button variant="light" className="rounded-xl" onPress={onClose}>
            {isEdit || mode === "write" ? "Cancel" : "Done"}
          </Button>
          {(isEdit || mode === "write") && (
            <Button
              color="primary"
              className="rounded-xl"
              onPress={handleSave}
              isLoading={saving}
              isDisabled={!isValid}
            >
              {isEdit ? "Save changes" : "Create skill"}
            </Button>
          )}
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
