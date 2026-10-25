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
// The renderer takes streamdown's Components, not react-markdown's: the two are
// structurally incompatible, and react-markdown's is not assignable to it.
import type { Components } from "streamdown";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import {
  InstructionsConflictNotice,
  MAX_INSTRUCTIONS_CHARS,
  type UseInstructionsResult,
} from "@/features/instructions";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { MentionChip } from "@/features/integrations/components/MentionChip";
import { MentionEditor } from "@/features/integrations/components/MentionEditor";
import type { Integration } from "@/features/integrations/types";
import {
  decodeMentionHref,
  MENTION_LINK_PROTOCOL,
  mentionsToMarkdownLinks,
} from "@/features/integrations/utils/toolMentions";
import { usePlatform } from "@/hooks/ui/usePlatform";

const MENTION_PROTOCOLS = [MENTION_LINK_PROTOCOL];

interface IntegrationInstructionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  integration: Integration;
  instructions: UseInstructionsResult;
  toolNames: string[];
}

export const IntegrationInstructionsModal = ({
  isOpen,
  onClose,
  integration,
  instructions,
  toolNames,
}: IntegrationInstructionsModalProps) => {
  const {
    draft: value,
    setDraft: setValue,
    isDirty,
    isSaving,
    isRefreshing,
    hasConflict,
    save,
    keepMine,
    loadLatest,
    discard,
  } = instructions;
  const [tab, setTab] = useState("write");
  const [wasOpen, setWasOpen] = useState(isOpen);
  const { isMac, modifierKeyName } = usePlatform();

  // Render-phase state adjustment, not an effect, avoids a stale frame.
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen) setTab("write");
  }

  // The draft lives in the hook, so closing without saving must drop it.
  const handleClose = useCallback(() => {
    discard();
    onClose();
  }, [discard, onClose]);

  const canMention = toolNames.length > 0;

  const renderMentionIcon = useCallback(
    () => (
      <IntegrationIcon
        integrationId={integration.id}
        iconUrl={integration.iconUrl}
        category={integration.category}
        size={16}
      />
    ),
    [integration.id, integration.iconUrl, integration.category],
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

  const canSave = isDirty && !isSaving && !hasConflict;

  const handleSave = useCallback(async () => {
    if (await save()) onClose();
  }, [save, onClose]);

  const handleKeepMine = useCallback(async () => {
    if (await keepMine()) onClose();
  }, [keepMine, onClose]);

  // Cmd/Ctrl+Enter saves. Mirror BearerTokenModal: a ref keeps the listener
  // stable while always reading the latest state. (Escape is handled by the
  // Modal's built-in dismiss.)
  const saveShortcutRef = useRef({ isMac, canSave, handleSave });
  useEffect(() => {
    saveShortcutRef.current = { isMac, canSave, handleSave };
  });

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
      onClose={handleClose}
      size="2xl"
      backdrop="blur"
      scrollBehavior="inside"
      className="rounded-2xl border border-zinc-800 bg-zinc-900/95 outline-0 backdrop-blur-3xl"
    >
      <ModalContent>
        <ModalHeader className="flex gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
            <IntegrationIcon
              integrationId={integration.id}
              iconUrl={integration.iconUrl}
              category={integration.category}
              size={26}
            />
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
                maxLength={MAX_INSTRUCTIONS_CHARS}
                placeholder={`e.g. Focus on #eng, #design, and #pm.\nNever post to #general.\nDefault to a friendly, concise tone.`}
              />

              <div className="mt-2 flex items-center justify-between text-xs font-light text-zinc-500">
                <span>
                  {canMention
                    ? "Type @ to mention a tool"
                    : "Markdown supported"}
                </span>
                <span>
                  {value.length} / {MAX_INSTRUCTIONS_CHARS}
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
                    Nothing to preview yet. Switch to Write and add some
                    guidance.
                  </p>
                )}
              </div>
            </Tab>
          </Tabs>

          {hasConflict && (
            <InstructionsConflictNotice
              isSaving={isSaving}
              isRefreshing={isRefreshing}
              onLoadLatest={loadLatest}
              onKeepMine={handleKeepMine}
            />
          )}
        </ModalBody>

        <ModalFooter>
          <Button
            variant="light"
            onPress={handleClose}
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
