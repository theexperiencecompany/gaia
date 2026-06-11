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
import { useEffect, useState, useTransition } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry } from "@/features/memory/api/types";
import { MAX_MEMORY_LENGTH } from "@/features/memory/constants";
import { toast } from "@/lib/toast";

interface EditMemoryModalProps {
  memory: MemoryEntry | null;
  onClose: () => void;
  onSaved: () => void;
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
    <Modal isOpen={memory !== null} onClose={onClose} size="lg">
      <ModalContent>
        <ModalHeader className="flex-col gap-1">
          <span>Edit memory</span>
          <span className="text-xs font-normal text-zinc-500">
            Saving keeps the previous version in this memory's history
          </span>
        </ModalHeader>
        <ModalBody>
          <Textarea
            value={content}
            onValueChange={setContent}
            minRows={3}
            maxRows={8}
            isInvalid={content.length > MAX_MEMORY_LENGTH}
            errorMessage={
              content.length > MAX_MEMORY_LENGTH
                ? `Keep it under ${MAX_MEMORY_LENGTH} characters`
                : undefined
            }
            autoFocus
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="light" className="rounded-xl" onPress={onClose}>
            Cancel
          </Button>
          <Button
            color="primary"
            className="rounded-xl"
            onPress={handleSave}
            isLoading={isPending}
            isDisabled={!content.trim() || content.length > MAX_MEMORY_LENGTH}
          >
            Save
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
