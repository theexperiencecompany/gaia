"use client";

import {
  Description,
  FieldError,
  Input,
  Label,
  Modal,
  Tabs,
  TextArea,
  TextField,
} from "@heroui/react";
import { Github01Icon } from "@icons";
import { useState } from "react";
import {
  modalVariants,
  tabsVariants,
} from "@/components/shared/controlVariants";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { toast } from "@/lib/toast";
import { skillsApi } from "../api/skillsApi";
import type {
  Skill,
  SkillInlineCreateRequest,
  SkillTarget,
} from "../api/types";
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

function skillNameError(name: string): string | undefined {
  if (!name) return undefined;
  if (name.length > MAX_SKILL_NAME_LENGTH)
    return `Keep it under ${MAX_SKILL_NAME_LENGTH} characters`;
  if (!SKILL_NAME_PATTERN.test(name) || CONSECUTIVE_HYPHENS.test(name))
    return "Lowercase letters, numbers, and single hyphens only";
  return undefined;
}

function skillDescriptionError(description: string): string | undefined {
  if (description.length > MAX_SKILL_DESCRIPTION_LENGTH)
    return `Keep it under ${MAX_SKILL_DESCRIPTION_LENGTH} characters`;
  return undefined;
}

/** The instructions editor, with a Markdown preview tab. */
function InstructionsField({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (value: string) => void }>) {
  const [tab, setTab] = useState<"write" | "preview">("write");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-300">Instructions</span>
        <Tabs
          className={shapeVariants({ shape: "pill" })}
          selectedKey={tab}
          onSelectionChange={(key) => setTab(key as "write" | "preview")}
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label="Instructions view">
              <Tabs.Tab id="write">
                Write
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="preview">
                Preview
                <Tabs.Indicator />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
      </div>
      {tab === "write" ? (
        <TextArea
          aria-label="Instructions"
          placeholder={"# Triage inbox\n\n1. Fetch unread mail\n2. ..."}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={10}
          className="font-mono text-xs"
        />
      ) : (
        <div className="min-h-44 rounded-xl bg-zinc-900/60 p-4">
          {value.trim() ? (
            <MarkdownRenderer
              content={value}
              hideCodeToolbar
              className="prose-sm prose-p:text-zinc-300 prose-li:text-zinc-300"
            />
          ) : (
            <p className="text-xs text-zinc-500">Nothing to preview yet.</p>
          )}
        </div>
      )}
    </div>
  );
}

/** Update skill when there is one, else create it from fields; toast which. */
async function saveSkill(
  skill: Skill | null,
  fields: SkillInlineCreateRequest,
) {
  const { name, ...changes } = fields;
  if (skill) {
    await skillsApi.updateSkill(skill.id, changes);
    toast.success(`Saved "${name}"`);
    return;
  }
  await skillsApi.createSkill(fields);
  toast.success(`Created "${name}"`);
}

function SkillEditorHeader({ isEdit }: Readonly<{ isEdit: boolean }>) {
  return (
    <Modal.Header className="flex-col items-start gap-1">
      <Modal.Heading>{isEdit ? "Edit skill" : "New skill"}</Modal.Heading>
      <span className="text-xs font-normal text-zinc-500">
        {isEdit
          ? "Update what this skill does and where it runs."
          : "Teach your assistant a reusable workflow it can follow."}
      </span>
    </Modal.Header>
  );
}

/** Whether the form can be saved. The name is immutable while editing, so its validity can't block a save (legacy skills may predate stricter name rules). */
function isSkillSavable(
  isEdit: boolean,
  fields: Pick<
    SkillInlineCreateRequest,
    "name" | "description" | "instructions"
  >,
): boolean {
  const nameValid =
    isEdit || (fields.name.length > 0 && !skillNameError(fields.name));
  return (
    nameValid &&
    fields.description.trim().length > 0 &&
    !skillDescriptionError(fields.description) &&
    fields.instructions.trim().length > 0
  );
}

function SkillEditorFooter({
  isEdit,
  isWriting,
  isSaving,
  isValid,
  onClose,
  onSave,
}: Readonly<{
  isEdit: boolean;
  /** False on the import tab, where there is nothing of this form's to save. */
  isWriting: boolean;
  isSaving: boolean;
  isValid: boolean;
  onClose: () => void;
  onSave: () => void;
}>) {
  return (
    <Modal.Footer>
      <GaiaButton variant="ghost" onPress={onClose}>
        {isWriting ? "Cancel" : "Done"}
      </GaiaButton>
      {isWriting && (
        <GaiaButton
          onPress={onSave}
          isPending={isSaving}
          isDisabled={!isValid}
          variant="primary"
        >
          {isEdit ? "Save changes" : "Create skill"}
        </GaiaButton>
      )}
    </Modal.Footer>
  );
}

/**
 * The modal's inner content. Rendered inside <ModalContent>, which HeroUI
 * unmounts when the modal closes — so this state initializes fresh from
 * `skill` on every open, with no reset-on-prop-change effect.
 */
function SkillEditorForm({
  onClose,
  onSaved,
  targets,
  skill,
}: Readonly<{
  onClose: () => void;
  onSaved: () => void;
  targets: SkillTarget[];
  skill: Skill | null;
}>) {
  const isEdit = skill !== null;

  const [mode, setMode] = useState<"write" | "import">("write");
  const [name, setName] = useState(skill?.name ?? "");
  const [target, setTarget] = useState<Skill["target"]>(
    skill?.target ?? EXECUTOR_TARGET,
  );
  const [description, setDescription] = useState(skill?.description ?? "");
  const [instructions, setInstructions] = useState(skill?.body_content ?? "");
  const [saving, setSaving] = useState(false);

  const nameError = skillNameError(name);
  const descriptionError = skillDescriptionError(description);

  const isValid = isSkillSavable(isEdit, { name, description, instructions });

  const handleSave = async () => {
    if (!isValid) return;
    setSaving(true);
    try {
      await saveSkill(skill, {
        name,
        description: description.trim(),
        instructions,
        target,
      });
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
      <TextField
        className={fieldVariants({ labelPlacement: "inside" })}
        value={name}
        onChange={setName}
        isDisabled={isEdit}
        isInvalid={!!nameError}
      >
        <Label>Name</Label>
        <Input placeholder="triage-inbox" />
        <Description>
          {isEdit
            ? "The name is the skill's identity and can't be changed."
            : "Lowercase, hyphenated. This is how the agent refers to it."}
        </Description>
        <FieldError>{nameError}</FieldError>
      </TextField>
      <TextField
        className={fieldVariants({ labelPlacement: "inside" })}
        value={description}
        onChange={setDescription}
        isInvalid={!!descriptionError}
      >
        <Label>Description</Label>
        <Input placeholder="Sort, label, and draft replies for new mail" />
        <Description>
          What it does and when to use it: the agent sees this at all times.
        </Description>
        <FieldError>{descriptionError}</FieldError>
      </TextField>
      <SkillTargetSelect
        targets={targets}
        value={target}
        onChange={setTarget}
      />
      <InstructionsField value={instructions} onChange={setInstructions} />
    </div>
  );

  return (
    <>
      <SkillEditorHeader isEdit={isEdit} />
      <Modal.Body>
        {isEdit ? (
          writeForm
        ) : (
          <Tabs
            selectedKey={mode}
            onSelectionChange={(key) => setMode(key as "write" | "import")}
            className={tabsVariants({
              color: "accent",
              className: shapeVariants({ shape: "pill", className: "mb-1" }),
            })}
          >
            <Tabs.ListContainer>
              <Tabs.List aria-label="Skill source">
                <Tabs.Tab id="write">
                  Write your own
                  <Tabs.Indicator />
                </Tabs.Tab>
                <Tabs.Tab id="import">
                  <div className="flex items-center gap-1.5">
                    <Github01Icon className="size-4" />
                    <span>Import from GitHub</span>
                  </div>
                  <Tabs.Indicator />
                </Tabs.Tab>
              </Tabs.List>
            </Tabs.ListContainer>
            <Tabs.Panel id="write">{writeForm}</Tabs.Panel>
            <Tabs.Panel id="import">
              <SkillImportForm targets={targets} onInstalled={onSaved} />
            </Tabs.Panel>
          </Tabs>
        )}
      </Modal.Body>
      <SkillEditorFooter
        isEdit={isEdit}
        isWriting={isEdit || mode === "write"}
        isSaving={saving}
        isValid={isValid}
        onClose={onClose}
        onSave={handleSave}
      />
    </>
  );
}

export function SkillEditorModal({
  isOpen,
  onClose,
  onSaved,
  targets,
  skill,
}: Readonly<SkillEditorModalProps>) {
  // Keyed on the skill being edited so swapping targets mid-open remounts the
  // form with the new skill's values.
  const formKey = `${isOpen ? "open" : "closed"}-${skill?.id ?? "new"}`;

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && onClose()}>
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog
            className={modalVariants({ size: "2xl", className: "max-w-2xl" })}
          >
            <Modal.CloseTrigger aria-label="Close" />
            <SkillEditorForm
              key={formKey}
              onClose={onClose}
              onSaved={onSaved}
              targets={targets}
              skill={skill}
            />
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
