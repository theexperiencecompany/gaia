"use client";

import {
  Button,
  Description,
  FieldError,
  Input,
  Label,
  Modal,
  TextArea,
  TextField,
} from "@heroui/react";
import { useState, useTransition } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
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
  const [wasOpen, setWasOpen] = useState(isOpen);

  // Clear the draft when the modal closes. Render-phase adjustment
  // (React: "adjusting state when a prop changes") instead of an effect,
  // so the reset commits with the same frame as the close.
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (!isOpen) {
      setContent("");
      setCategoryPath("");
    }
  }

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
    <Modal isOpen={isOpen} onOpenChange={onClose}>
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex-col gap-1">
              <span>Add memory</span>
              <span className="text-xs font-normal text-zinc-500">
                Tell GAIA something specific about yourself, your preferences,
                or details worth remembering
              </span>
            </Modal.Header>
            <Modal.Body>
              <TextField
                value={content}
                onChange={setContent}
                isInvalid={content.length > MAX_MEMORY_LENGTH}
              >
                <TextArea
                  placeholder="e.g. I'm vegetarian and allergic to peanuts"
                  rows={3}
                  autoFocus
                />
                <FieldError>
                  {content.length > MAX_MEMORY_LENGTH
                    ? `Keep it under ${MAX_MEMORY_LENGTH} characters`
                    : undefined}
                </FieldError>
              </TextField>
              <TextField
                className={inputVariants({ size: "sm" })}
                value={categoryPath}
                onChange={setCategoryPath}
              >
                <Label>Folder</Label>
                <Input placeholder="e.g. food-preferences" />
                <Description>
                  Optional. GAIA files it automatically when left blank.
                </Description>
              </TextField>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" className="rounded-xl" onPress={onClose}>
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
                Save memory
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
