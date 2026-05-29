"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import { useEffect, useRef, useState } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { MentionTextarea } from "@/features/integrations/components/MentionTextarea";

// Matches the backend cap in integration_instructions_models.py
const MAX_CHARS = 8000;

interface IntegrationInstructionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  integrationName: string;
  savedContent: string;
  isSaving: boolean;
  toolNames: string[];
  onSave: (content: string) => Promise<void>;
}

export const IntegrationInstructionsModal = ({
  isOpen,
  onClose,
  integrationName,
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
        <ModalHeader className="flex flex-col gap-1">
          <span className="text-lg font-semibold text-zinc-100">
            Custom instructions
          </span>
          <span className="text-sm font-light text-zinc-400">
            Standing guidance GAIA follows whenever it uses {integrationName}.
            {canMention ? " Type @ to mention a tool." : ""} Markdown supported.
          </span>
        </ModalHeader>

        <ModalBody className="gap-3">
          <Tabs
            aria-label="Instructions editor"
            selectedKey={tab}
            onSelectionChange={(key) => setTab(String(key))}
            variant="solid"
            size="sm"
            classNames={{ tabList: "bg-zinc-800/60", cursor: "bg-zinc-700" }}
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

              <div className="mt-1 flex items-center justify-between text-xs font-light text-zinc-500">
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
