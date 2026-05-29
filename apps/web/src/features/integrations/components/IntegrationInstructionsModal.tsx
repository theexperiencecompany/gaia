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
import { useToolMention } from "@/features/integrations/hooks/useToolMention";

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
  const mention = useToolMention({ onChange: setValue, toolNames });

  // Reset the draft to the persisted content every time the modal opens.
  useEffect(() => {
    if (isOpen) {
      setValue(savedContent);
      setTab("write");
    }
  }, [isOpen, savedContent]);

  const isDirty = value.trim() !== savedContent.trim();
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
              <div className="relative">
                <Textarea
                  autoFocus
                  value={value}
                  onValueChange={setValue}
                  minRows={10}
                  maxRows={18}
                  maxLength={MAX_CHARS}
                  placeholder={`e.g. Focus on #eng, #design, and #pm.\nNever post to #general.\nDefault to a friendly, concise tone.`}
                  classNames={{
                    input:
                      "font-mono text-sm leading-relaxed placeholder:text-zinc-600",
                    inputWrapper:
                      "rounded-2xl border border-zinc-800 bg-zinc-800/40 shadow-none transition-colors hover:bg-zinc-800/40 group-data-[focus=true]:border-zinc-700 group-data-[focus=true]:bg-zinc-800/40 group-data-[focus-visible=true]:ring-transparent group-data-[focus-visible=true]:ring-offset-0",
                  }}
                  {...mention.textareaHandlers}
                />

                {mention.isOpen && (
                  <div className="mt-2 max-h-52 overflow-y-auto rounded-2xl border border-zinc-700 bg-zinc-900 p-1 shadow-xl">
                    <p className="px-3 py-1.5 text-xs font-light text-zinc-500">
                      Mention a tool
                    </p>
                    {mention.matches.map((name, idx) => (
                      <button
                        type="button"
                        key={name}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          mention.insert(name);
                        }}
                        onMouseEnter={() => mention.setHighlight(idx)}
                        className={`flex w-full items-center rounded-xl px-3 py-2 text-left text-sm transition-colors ${
                          idx === mention.highlight
                            ? "bg-zinc-800 text-zinc-100"
                            : "text-zinc-300"
                        }`}
                      >
                        <span className="truncate">{name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

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
