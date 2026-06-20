"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Github01Icon, PlusSignIcon } from "@icons";
import { useMemo, useState } from "react";
import { toast } from "@/lib/toast";
import { skillsApi } from "../api/skillsApi";
import type { DiscoveredSkill, SkillTarget } from "../api/types";
import { EXECUTOR_TARGET, GITHUB_REPO_PATTERN } from "../constants";
import { SkillTargetSelect } from "./SkillTargetSelect";

interface SkillImportFormProps {
  targets: SkillTarget[];
  /** Called after each successful install so the caller can refetch. */
  onInstalled: () => void;
}

/** The "Import from GitHub" tab: discover a repo's skills and install them. */
export function SkillImportForm({
  targets,
  onInstalled,
}: SkillImportFormProps) {
  const [target, setTarget] = useState(EXECUTOR_TARGET);
  const [repoUrl, setRepoUrl] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredSkill[] | null>(null);
  const [discoverError, setDiscoverError] = useState(false);
  const [installingPath, setInstallingPath] = useState<string | null>(null);
  const [installingAll, setInstallingAll] = useState(false);

  // No install (single or "Add all") may overlap another.
  const installBusy = installingAll || installingPath !== null;

  const repoError = useMemo(() => {
    const repo = repoUrl.trim();
    if (!repo) return undefined;
    if (!GITHUB_REPO_PATTERN.test(repo))
      return "Use owner/repo or a full github.com URL";
    return undefined;
  }, [repoUrl]);
  const repoValid = repoUrl.trim().length > 0 && !repoError;

  const handleDiscover = async () => {
    const repo = repoUrl.trim();
    if (!repo) return;
    setDiscovering(true);
    setDiscovered(null);
    setDiscoverError(false);
    try {
      const result = await skillsApi.discoverSkills(repo);
      setDiscovered(result.skills);
      if (result.skills.length === 0)
        toast.info("No skills found in that repo");
    } catch {
      setDiscoverError(true);
    } finally {
      setDiscovering(false);
    }
  };

  const handleInstall = async (skill: DiscoveredSkill) => {
    if (installBusy) return;
    setInstallingPath(skill.path);
    try {
      await skillsApi.installFromGithub(
        skill.repo_url,
        skill.name,
        skill.path,
        target,
      );
      toast.success(`Installed "${skill.name}"`);
      onInstalled();
    } catch {
      // Interceptor surfaces the error (e.g. already installed).
    } finally {
      setInstallingPath(null);
    }
  };

  const handleInstallAll = async () => {
    if (installBusy || !discovered?.length) return;
    setInstallingAll(true);
    let installed = 0;
    // Sequential to stay friendly to GitHub rate limits and keep order stable.
    for (const skill of discovered) {
      try {
        await skillsApi.installFromGithub(
          skill.repo_url,
          skill.name,
          skill.path,
          target,
        );
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
      onInstalled();
    } else {
      toast.error("Couldn't add any skills");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <SkillTargetSelect
        targets={targets}
        value={target}
        onChange={setTarget}
      />
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
              isDisabled={installBusy && !installingAll}
              startContent={
                installingAll ? undefined : <PlusSignIcon className="size-4" />
              }
              onPress={handleInstallAll}
            >
              Add all
            </Button>
          </div>
          <div className="divide-y divide-zinc-800/60 overflow-hidden rounded-xl bg-zinc-800/60">
            {discovered.map((skill) => (
              <div
                key={`${skill.repo_url}/${skill.path}`}
                className="flex items-center gap-3 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-zinc-100">{skill.name}</p>
                  <p className="line-clamp-1 text-xs text-zinc-500">
                    {skill.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  color="primary"
                  variant="flat"
                  className="rounded-xl"
                  isLoading={installingPath === skill.path}
                  isDisabled={installBusy && installingPath !== skill.path}
                  startContent={
                    installingPath === skill.path ? undefined : (
                      <PlusSignIcon className="size-4" />
                    )
                  }
                  onPress={() => handleInstall(skill)}
                >
                  Add
                </Button>
              </div>
            ))}
          </div>
        </>
      )}
      {discoverError && (
        <p className="text-center text-xs text-zinc-500">
          Couldn't reach that repository. Check the name and try again.
        </p>
      )}
      {!discoverError &&
        discovered !== null &&
        discovered.length === 0 &&
        !discovering && (
          <p className="text-center text-xs text-zinc-500">
            No skills found in that repository.
          </p>
        )}
    </div>
  );
}
