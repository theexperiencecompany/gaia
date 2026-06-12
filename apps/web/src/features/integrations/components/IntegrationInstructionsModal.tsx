"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import { useEffect, useMemo, useRef, useState } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { MentionTextarea } from "@/features/integrations/components/MentionTextarea";
import type { Integration } from "@/features/integrations/types";
import {
  extractMentionedTools,
  removeToolMention,
} from "@/features/integrations/utils/toolMentions";

// Matches the backend cap in integration_instructions_models.py
const MAX_CHARS = 8000;

interface IntegrationInstructionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  integration: Integration;
  savedContent: string;
  isSaving: boolean;
  toolNames: string[];
  onSave: (content: string) => Promise<void>;
}

interface MentionedToolChipsProps {
  names: string[];
  integration: Integration;
  onRemove?: (name: string) => void;
}

const MentionedToolChips = ({
  names,
  integration,
  onRemove,
}: MentionedToolChipsProps) => {
  if (names.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {names.map((name) => (
        <Chip
          key={name}
          size="sm"
          variant="flat"
          radius="full"
          startContent={getToolCategoryIcon(
            integration.id,
            { size: 14, width: 14, height: 14, showBackground: false },
            integration.iconUrl,
          )}
          onClose={onRemove ? () => onRemove(name) : undefined}
        >
          {name}
        </Chip>
      ))}
    </div>
  );
};

export const IntegrationInstructionsModal = ({
  isOpen,
  onClose,
  integration,
  savedContent,
  isSaving,
  toolNames,
  onSave,
}: IntegrationInstructionsModalProps) => {
  const [value, setValue] = useState(savedContent);
  const [tab, setTab] = useState("write");
  const wasOpenRef = useRef(false);

  // Reset the draft to the persisted content only on the closed->open
  // transition — not on every savedContent change, which would clobber
  // in-progress edits if the query refetches while the modal is open.
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      setValue(savedContent);
      setTab("write");
    }
    wasOpenRef.current = isOpen;
  }, [isOpen, savedContent]);

  // Raw compare: leading/trailing whitespace can be meaningful in Markdown,
  // and the backend already normalizes whitespace-only content to empty.
  const isDirty = value !== savedContent;
  const canMention = toolNames.length > 0;

  const mentionedTools = useMemo(
    () => extractMentionedTools(value, toolNames),
    [value, toolNames],
  );

  const handleSave = async () => {
    await onSave(value);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      backdrop="blur"
      scrollBehavior="inside"
      className="rounded-2xl border border-zinc-800 bg-zinc-900/95 outline-0 backdrop-blur-3xl"
    >
      <ModalContent>
        <ModalHeader className="flex gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
            {getToolCategoryIcon(
              integration.id,
              { size: 26, width: 26, height: 26, showBackground: false },
              integration.iconUrl,
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-lg font-semibold text-zinc-100">
              Custom instructions for {integration.name}
            </span>
            <span className="text-sm font-light text-zinc-400">
              Tell GAIA how you use {integration.name} — preferences, defaults,
              and things to avoid. Applied every time GAIA works with it.
              {canMention ? " Type @ to mention a specific tool." : ""} Markdown
              supported.
            </span>
          </div>
        </ModalHeader>

        <ModalBody className="gap-3">
          <Tabs
            aria-label="Instructions editor"
            selectedKey={tab}
            onSelectionChange={(key) => setTab(String(key))}
            variant="solid"
            classNames={{
              tabList: "bg-zinc-800/60",
              cursor: "bg-zinc-700",
              panel: "px-0 pb-0 pt-2",
            }}
          >
            <Tab key="write" title="Write">
              <MentionTextarea
                value={value}
                onChange={setValue}
                toolNames={toolNames}
                maxLength={MAX_CHARS}
                rows={10}
                placeholder={`e.g. Focus on #eng, #design, and #pm.\nNever post to #general.\nDefault to a friendly, concise tone.`}
              />

              <MentionedToolChips
                names={mentionedTools}
                integration={integration}
                onRemove={(name) => setValue(removeToolMention(value, name))}
              />

              <div className="mt-2 flex items-center justify-between text-xs font-light text-zinc-500">
                <span>
                  {canMention
                    ? "Type @ to mention a tool"
                    : "Markdown supported"}
                </span>
                <span>
                  {value.length} / {MAX_CHARS}
                </span>
              </div>
            </Tab>

            <Tab key="preview" title="Preview">
              <div className="min-h-[16rem] rounded-2xl bg-zinc-800/50 p-4">
                {value.trim() ? (
                  <MarkdownRenderer content={value} className="text-sm" />
                ) : (
                  <p className="py-12 text-center text-sm text-zinc-500">
                    Nothing to preview yet — switch to Write and add some
                    guidance.
                  </p>
                )}
              </div>

              <MentionedToolChips
                names={mentionedTools}
                integration={integration}
              />
            </Tab>
          </Tabs>
        </ModalBody>

        <ModalFooter>
          <Button variant="light" onPress={onClose} isDisabled={isSaving}>
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={handleSave}
            isLoading={isSaving}
            isDisabled={!isDirty || isSaving}
          >
            Save instructions
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
