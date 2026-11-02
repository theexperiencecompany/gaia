"use client";

import {
  Button,
  FieldError,
  Label,
  Modal,
  TextArea,
  TextField,
} from "@heroui/react";
import type { MemoryEntry } from "@shared/api/generated";
import { useEffect, useState, useTransition } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { MAX_MEMORY_LENGTH } from "@/features/memory/constants";
import { toast } from "@/lib/toast";

interface EditMemoryModalProps {
  readonly memory: MemoryEntry | null;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

export function EditMemoryModal({
  memory,
  onClose,
  onSaved,
}: EditMemoryModalProps) {
  const [content, setContent] = useState("");
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (memory) setContent(memory.content);
  }, [memory]);

  const handleSave = () => {
    if (!memory?.id || !content.trim()) return;
    const memoryId = memory.id;

    startTransition(async () => {
      try {
        await memoryApi.updateMemory(memoryId, content.trim());
        toast.success("Memory updated");
        onSaved();
        onClose();
      } catch {
        toast.error("Failed to update memory");
      }
    });
  };

  return (
    <Modal
      isOpen={memory !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex-col gap-1">
              <Modal.Heading>Edit memory</Modal.Heading>
              <span className="text-xs font-normal text-zinc-500">
                Saving keeps the previous version in this memory's history
              </span>
            </Modal.Header>
            <Modal.Body>
              <TextField
                value={content}
                onChange={setContent}
                isInvalid={content.length > MAX_MEMORY_LENGTH}
              >
                <Label className="sr-only">Memory content</Label>
                <TextArea rows={3} autoFocus />
                {content.length > MAX_MEMORY_LENGTH && (
                  <FieldError>
                    Keep it under {MAX_MEMORY_LENGTH} characters
                  </FieldError>
                )}
              </TextField>
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="tertiary"
                className="rounded-xl"
                onPress={onClose}
              >
                Cancel
              </Button>
              <Button
                className="rounded-xl"
                onPress={handleSave}
                isPending={isPending}
                isDisabled={
                  !content.trim() || content.length > MAX_MEMORY_LENGTH
                }
                variant="primary"
              >
                Save
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
