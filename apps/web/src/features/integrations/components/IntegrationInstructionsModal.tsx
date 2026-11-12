"use client";

import { Kbd, Modal, Tabs } from "@heroui/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
// The renderer takes streamdown's Components, not react-markdown's: the two are
// structurally incompatible, and react-markdown's is not assignable to it.
import type { Components } from "streamdown";
import { modalVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <Modal.Backdrop variant="blur">
        <Modal.Container placement="center">
          <Modal.Dialog
            className={modalVariants({
              size: "2xl",
              className:
                "max-w-2xl border border-zinc-800 bg-zinc-900/95 outline-0 backdrop-blur-3xl",
            })}
          >
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex gap-3">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
                <IntegrationIcon
                  integrationId={integration.id}
                  iconUrl={integration.iconUrl}
                  category={integration.category}
                  size={26}
                />
              </div>
              <div className="flex min-w-0 flex-col gap-0.5">
                <Modal.Heading className="text-lg font-semibold">
                  Custom instructions for {integration.name}
                </Modal.Heading>
                <span className="text-sm font-light text-zinc-400">
                  Tell GAIA how you use {integration.name}.
                  {canMention ? " Type @ to mention a tool." : ""} Markdown
                  supported.
                </span>
              </div>
            </Modal.Header>

            <Modal.Body className="gap-3">
              <Tabs
                selectedKey={tab}
                onSelectionChange={(key) => setTab(String(key))}
                variant="primary"
              >
                <Tabs.List
                  aria-label="Instructions editor"
                  className="bg-zinc-800/60"
                >
                  <Tabs.Tab id="write">
                    Write
                    <Tabs.Indicator className="bg-zinc-700" />
                  </Tabs.Tab>
                  <Tabs.Tab id="preview">
                    Preview
                    <Tabs.Indicator className="bg-zinc-700" />
                  </Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel id="write" className="px-0 pb-0">
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
                </Tabs.Panel>

                <Tabs.Panel id="preview" className="px-0 pb-0">
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
                </Tabs.Panel>
              </Tabs>

              {hasConflict && (
                <InstructionsConflictNotice
                  isSaving={isSaving}
                  isRefreshing={isRefreshing}
                  onLoadLatest={loadLatest}
                  onKeepMine={handleKeepMine}
                />
              )}
            </Modal.Body>

            <Modal.Footer>
              <GaiaButton
                variant="ghost"
                onPress={handleClose}
                isDisabled={isSaving}
              >
                Cancel
                <Kbd>
                  <Kbd.Abbr keyValue="escape" />
                </Kbd>
              </GaiaButton>
              <GaiaButton
                onPress={handleSave}
                isPending={isSaving}
                isDisabled={!canSave}
                variant="primary"
              >
                Save instructions
                {!isSaving && (
                  <Kbd>
                    <Kbd.Abbr keyValue={modifierKeyName} />
                    <Kbd.Abbr keyValue="enter" />
                  </Kbd>
                )}
              </GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
};
