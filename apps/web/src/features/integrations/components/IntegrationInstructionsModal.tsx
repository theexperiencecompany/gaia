"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tab, Tabs } from "@heroui/tabs";
import { useEffect, useState } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

// Matches the backend cap in integration_instructions_models.py
const MAX_CHARS = 8000;

interface IntegrationInstructionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  integrationName: string;
  savedContent: string;
  isSaving: boolean;
  onSave: (content: string) => Promise<void>;
}

export const IntegrationInstructionsModal = ({
  isOpen,
  onClose,
  integrationName,
  savedContent,
  isSaving,
  onSave,
}: IntegrationInstructionsModalProps) => {
  const [value, setValue] = useState(savedContent);
  const [tab, setTab] = useState("write");

  // Reset the draft to the persisted content every time the modal opens.
  useEffect(() => {
    if (isOpen) {
      setValue(savedContent);
      setTab("write");
    }
  }, [isOpen, savedContent]);

  const isDirty = value.trim() !== savedContent.trim();

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
      className="rounded-2xl bg-zinc-900/95 backdrop-blur-3xl outline-0 border border-zinc-800"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <span className="text-lg font-semibold text-zinc-100">
            Custom instructions
          </span>
          <span className="text-sm font-light text-zinc-400">
            Standing guidance GAIA follows whenever it uses {integrationName}.
            Markdown supported.
          </span>
        </ModalHeader>

        <ModalBody className="gap-3">
          <Tabs
            aria-label="Instructions editor"
            selectedKey={tab}
            onSelectionChange={(key) => setTab(String(key))}
            variant="solid"
            size="sm"
            classNames={{ tabList: "bg-zinc-800/60" }}
          >
            <Tab key="write" title="Write">
              <Textarea
                autoFocus
                value={value}
                onValueChange={setValue}
                minRows={14}
                maxRows={20}
                maxLength={MAX_CHARS}
                variant="bordered"
                placeholder={`e.g. Focus on #eng, #design, and #pm.\nNever post to #general.\nDefault to a friendly, concise tone.`}
                classNames={{ input: "font-mono text-sm leading-relaxed" }}
              />
              <div className="mt-1 text-right text-xs font-light text-zinc-500">
                {value.length} / {MAX_CHARS}
              </div>
            </Tab>
            <Tab key="preview" title="Preview">
              <div className="min-h-[18rem] rounded-2xl bg-zinc-800/50 p-4">
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
