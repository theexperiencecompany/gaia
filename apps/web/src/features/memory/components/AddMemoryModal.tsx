"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { useEffect, useState, useTransition } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { MAX_MEMORY_LENGTH } from "@/features/memory/constants";
import { toast } from "@/lib/toast";

interface AddMemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onMemoryAdded: () => void;
}

export function AddMemoryModal({
  isOpen,
  onClose,
  onMemoryAdded,
}: AddMemoryModalProps) {
  const [content, setContent] = useState("");
  const [categoryPath, setCategoryPath] = useState("");
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!isOpen) {
      setContent("");
      setCategoryPath("");
    }
  }, [isOpen]);

  const handleSave = () => {
    if (!content.trim()) return;

    startTransition(async () => {
      try {
        const response = await memoryApi.createMemory({
          content: content.trim(),
          category_path: categoryPath.trim() || undefined,
        });
        if (response.success) {
          toast.success("Memory added");
          onMemoryAdded();
          onClose();
        } else {
          toast.error(response.message || "Failed to add memory");
        }
      } catch {
        toast.error("Failed to add memory");
      }
    });
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalContent>
        <ModalHeader className="flex-col gap-1">
          <span>Add memory</span>
          <span className="text-xs font-normal text-zinc-500">
            Tell GAIA something specific about yourself, your preferences, or
            details worth remembering
          </span>
        </ModalHeader>
        <ModalBody>
          <Textarea
            placeholder="e.g. I'm vegetarian and allergic to peanuts"
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
          <Input
            label="Folder"
            labelPlacement="outside"
            placeholder="e.g. food-preferences"
            description="Optional. GAIA files it automatically when left blank."
            value={categoryPath}
            onValueChange={setCategoryPath}
            size="sm"
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
            Save memory
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
