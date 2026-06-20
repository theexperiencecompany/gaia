"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { SkillTargetIcon } from "./SkillTargetIcon";

/** Normalized shape for the shared read-only preview (built-in or user skill). */
export interface SkillPreview {
  name: string;
  description: string;
  /** SKILL.md markdown body. */
  body: string;
  /** Display name of the owning agent (e.g. "General assistant", "Gmail"). */
  groupLabel: string;
  /** Icon key for SkillTargetIcon (subagent/integration id, or "executor"). */
  icon: string;
  /** Optional prefix tag, e.g. "Built-in". */
  badge?: string;
}

interface SkillPreviewModalProps {
  skill: SkillPreview | null;
  onClose: () => void;
}

/** Read-only preview of a skill's SKILL.md — shared by Your Skills and Built-in. */
export function SkillPreviewModal({ skill, onClose }: SkillPreviewModalProps) {
  return (
    <Modal
      isOpen={skill !== null}
      onClose={onClose}
      size="2xl"
      scrollBehavior="inside"
    >
      <ModalContent>
        {skill && (
          <>
            <ModalHeader className="flex items-center gap-3">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
                <SkillTargetIcon
                  value={skill.icon}
                  icon={skill.icon}
                  size={20}
                />
              </div>
              <div className="min-w-0">
                <p className="truncate text-base font-medium text-white">
                  {skill.name}
                </p>
                <p className="text-xs font-normal text-zinc-500">
                  {skill.badge
                    ? `${skill.badge} · ${skill.groupLabel}`
                    : skill.groupLabel}
                </p>
              </div>
            </ModalHeader>
            <ModalBody>
              {skill.description && (
                <p className="text-sm text-zinc-400">{skill.description}</p>
              )}
              {skill.body && (
                <div className="rounded-xl bg-zinc-900/60 p-4">
                  <MarkdownRenderer
                    content={skill.body}
                    hideCodeToolbar
                    className="prose-sm prose-p:text-zinc-300 prose-li:text-zinc-300"
                  />
                </div>
              )}
            </ModalBody>
            <ModalFooter>
              <Button variant="light" className="rounded-xl" onPress={onClose}>
                Close
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
