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
import { Select, SelectItem } from "@heroui/select";
import { Tab, Tabs } from "@heroui/tabs";
import { Github01Icon, PlusSignIcon } from "@icons";
import { useEffect, useMemo, useState } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { toast } from "@/lib/toast";
import { skillsApi } from "../api/skillsApi";
import type { DiscoveredSkill, Skill, SkillTarget } from "../api/types";
import {
  EXECUTOR_TARGET,
  GITHUB_REPO_PATTERN,
  MAX_SKILL_DESCRIPTION_LENGTH,
  MAX_SKILL_NAME_LENGTH,
  SKILL_NAME_PATTERN,
} from "../constants";
import { SkillTargetIcon } from "./SkillTargetIcon";

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
}: SkillEditorModalProps) {
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

  // Import-from-GitHub state.
  const [repoUrl, setRepoUrl] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredSkill[] | null>(null);
  const [installingName, setInstallingName] = useState<string | null>(null);
  const [installingAll, setInstallingAll] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setMode("write");
    setInstructionsTab("write");
    setName(skill?.name ?? "");
    setTarget(skill?.target ?? EXECUTOR_TARGET);
    setDescription(skill?.description ?? "");
    setInstructions(skill?.body_content ?? "");
    setRepoUrl("");
    setDiscovered(null);
    setInstallingName(null);
    setInstallingAll(false);
  }, [isOpen, skill]);

  const nameError = useMemo(() => {
    if (!name) return undefined;
    if (name.length > MAX_SKILL_NAME_LENGTH)
      return `Keep it under ${MAX_SKILL_NAME_LENGTH} characters`;
    if (!SKILL_NAME_PATTERN.test(name))
      return "Use lowercase letters, numbers, and single hyphens";
    return undefined;
  }, [name]);

  const repoError = useMemo(() => {
    const repo = repoUrl.trim();
    if (!repo) return undefined;
    if (!GITHUB_REPO_PATTERN.test(repo))
      return "Use owner/repo or a full github.com URL";
    return undefined;
  }, [repoUrl]);

  const repoValid = repoUrl.trim().length > 0 && !repoError;

  const isValid =
    name.length > 0 &&
    !nameError &&
    description.trim().length > 0 &&
    description.length <= MAX_SKILL_DESCRIPTION_LENGTH &&
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

  const handleDiscover = async () => {
    const repo = repoUrl.trim();
    if (!repo) return;
    setDiscovering(true);
    setDiscovered(null);
    try {
      const result = await skillsApi.discoverSkills(repo);
      setDiscovered(result.skills);
      if (result.skills.length === 0)
        toast.info("No skills found in that repo");
    } catch {
      setDiscovered([]);
    } finally {
      setDiscovering(false);
    }
  };

  const handleInstall = async (discoveredSkill: DiscoveredSkill) => {
    setInstallingName(discoveredSkill.name);
    try {
      await skillsApi.installFromGithub(
        discoveredSkill.repo_url,
        discoveredSkill.name,
        target,
      );
      toast.success(`Installed "${discoveredSkill.name}"`);
      onSaved();
    } catch {
      // Interceptor surfaces the error (e.g. already installed).
    } finally {
      setInstallingName(null);
    }
  };

  const handleInstallAll = async () => {
    if (!discovered?.length) return;
    setInstallingAll(true);
    let installed = 0;
    // Sequential to stay friendly to GitHub rate limits and keep order stable.
    for (const d of discovered) {
      try {
        await skillsApi.installFromGithub(d.repo_url, d.name, target);
        installed += 1;
      } catch {
        // Skip ones that fail (e.g. already installed); keep going.
      }
    }
    setInstallingAll(false);
    if (installed > 0) {
      toast.success(
        `Installed ${installed} skill${installed === 1 ? "" : "s"}`,
      );
      onSaved();
    }
  };

  const targetSelect = (
    <Select
      label="Runs in"
      selectedKeys={[target]}
      onChange={(e) => e.target.value && setTarget(e.target.value)}
      classNames={{ trigger: "rounded-xl bg-zinc-800" }}
      renderValue={(items) => {
        const value = items[0]?.key as string | undefined;
        const meta = targets.find((t) => t.value === value);
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
      />
      {targetSelect}
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

  const importForm = (
    <div className="flex flex-col gap-4">
      {targetSelect}
      <Input
        label="GitHub repository"
        placeholder="owner/repo or a full GitHub URL"
        value={repoUrl}
        onValueChange={setRepoUrl}
        isInvalid={!!repoError}
        errorMessage={repoError}
        startContent={<Github01Icon className="size-4 text-white" />}
        onKeyDown={(e) => {
          if (e.key === "Enter" && repoValid) handleDiscover();
        }}
        endContent={
          <Button
            size="sm"
            color="primary"
            variant="flat"
            className="-mr-1 shrink-0 rounded-lg"
            isLoading={discovering}
            isDisabled={!repoValid}
            onPress={handleDiscover}
          >
            Find skills
          </Button>
        }
      />

      {discovered !== null && discovered.length > 0 && (
        <>
          <div className="flex items-center justify-between px-1">
            <span className="text-xs text-zinc-500">
              Found {discovered.length} skill
              {discovered.length === 1 ? "" : "s"}
            </span>
            <Button
              size="sm"
              color="primary"
              variant="flat"
              className="rounded-xl"
              isLoading={installingAll}
              startContent={
                installingAll ? undefined : <PlusSignIcon className="size-4" />
              }
              onPress={handleInstallAll}
            >
              Add all
            </Button>
          </div>
          <div className="divide-y divide-zinc-800/60 overflow-hidden rounded-xl bg-zinc-800/60">
            {discovered.map((d) => (
              <div
                key={`${d.repo_url}/${d.path}`}
                className="flex items-center gap-3 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-zinc-100">{d.name}</p>
                  <p className="line-clamp-1 text-xs text-zinc-500">
                    {d.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  color="primary"
                  variant="flat"
                  className="rounded-xl"
                  isLoading={installingName === d.name}
                  startContent={
                    installingName === d.name ? undefined : (
                      <PlusSignIcon className="size-4" />
                    )
                  }
                  onPress={() => handleInstall(d)}
                >
                  Add
                </Button>
              </div>
            ))}
          </div>
        </>
      )}
      {discovered !== null && discovered.length === 0 && !discovering && (
        <p className="text-center text-xs text-zinc-500">
          No skills found in that repository.
        </p>
      )}
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
                {importForm}
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
