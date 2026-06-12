"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Components } from "react-markdown";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { MentionChip } from "@/features/integrations/components/MentionChip";
import { MentionEditor } from "@/features/integrations/components/MentionEditor";
import type { Integration } from "@/features/integrations/types";
import {
  decodeMentionHref,
  MENTION_LINK_PROTOCOL,
  mentionsToMarkdownLinks,
} from "@/features/integrations/utils/toolMentions";
import { usePlatform } from "@/hooks/ui/usePlatform";

// Matches the backend cap in integration_instructions_models.py
const MAX_CHARS = 8000;

const MENTION_PROTOCOLS = [MENTION_LINK_PROTOCOL];

interface IntegrationInstructionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  integration: Integration;
  savedContent: string;
  isSaving: boolean;
  toolNames: string[];
  onSave: (content: string) => Promise<void>;
}

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
  const { isMac, modifierKeyName } = usePlatform();

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

  const renderMentionIcon = useCallback(
    () =>
      getToolCategoryIcon(
        integration.id,
        { size: 16, width: 16, height: 16, showBackground: false },
        integration.iconUrl,
      ),
    [integration.id, integration.iconUrl],
  );

  // Preview: mentions become `mention:` links the anchor override renders as
  // chips, so they look the same as in the editor.
  const previewContent = useMemo(
    () => mentionsToMarkdownLinks(value, toolNames),
    [value, toolNames],
  );

  const previewComponents = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        const name = typeof href === "string" ? decodeMentionHref(href) : null;
        if (name !== null) {
          return (
            <span className="mx-0.5 inline-flex translate-y-0.5">
              <MentionChip name={name} icon={renderMentionIcon()} />
            </span>
          );
        }
        return <CustomAnchor href={href}>{children}</CustomAnchor>;
      },
    }),
    [renderMentionIcon],
  );

  const canSave = isDirty && !isSaving;

  const handleSave = useCallback(async () => {
    await onSave(value);
    onClose();
  }, [onSave, value, onClose]);

  // Cmd/Ctrl+Enter saves. Mirror BearerTokenModal: a ref keeps the listener
  // stable while always reading the latest state. (Escape is handled by the
  // Modal's built-in dismiss.)
  const saveShortcutRef = useRef({ isMac, canSave, handleSave });
  saveShortcutRef.current = { isMac, canSave, handleSave };

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      const {
        isMac: mac,
        canSave: allowed,
        handleSave: save,
      } = saveShortcutRef.current;
      const modifier = mac ? e.metaKey : e.ctrlKey;
      if (modifier && e.key === "Enter" && allowed) {
        e.preventDefault();
        void save();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

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
              Tell GAIA how you use {integration.name}.
              {canMention ? " Type @ to mention a tool." : ""} Markdown
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
              <MentionEditor
                value={value}
                onChange={setValue}
                toolNames={toolNames}
                renderMentionIcon={renderMentionIcon}
                maxLength={MAX_CHARS}
                placeholder={`e.g. Focus on #eng, #design, and #pm.\nNever post to #general.\nDefault to a friendly, concise tone.`}
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
              <div className="min-h-60 rounded-2xl bg-zinc-800/50 p-4">
                {value.trim() ? (
                  <MarkdownRenderer
                    content={previewContent}
                    className="text-sm"
                    components={previewComponents}
                    extraLinkProtocols={MENTION_PROTOCOLS}
                  />
                ) : (
                  <p className="py-12 text-center text-sm text-zinc-500">
                    Nothing to preview yet — switch to Write and add some
                    guidance.
                  </p>
                )}
              </div>
            </Tab>
          </Tabs>
        </ModalBody>

        <ModalFooter>
          <Button
            variant="light"
            onPress={onClose}
            isDisabled={isSaving}
            endContent={<Kbd keys={["escape"]} />}
          >
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={handleSave}
            isLoading={isSaving}
            isDisabled={!canSave}
            endContent={!isSaving && <Kbd keys={[modifierKeyName, "enter"]} />}
          >
            Save instructions
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
