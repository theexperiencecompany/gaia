"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { memoryApi } from "@/features/memory/api/memoryApi";
import { X } from "@/icons";

interface AddMemoryFormProps {
  isOpen: boolean;
  onClose: () => void;
  onMemoryAdded: () => void;
}

const MAX_MEMORY_LENGTH = 500; // Set a reasonable character limit

export default function AddMemoryForm({
  isOpen,
  onClose,
  onMemoryAdded,
}: AddMemoryFormProps) {
  const [content, setContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Focus the textarea when the form opens
  useEffect(() => {
    if (isOpen && textareaRef.current) {
      // Small delay to ensure form is fully rendered
      setTimeout(() => {
        textareaRef.current?.focus();
      }, 50);
    }
  }, [isOpen]);

  // Reset content when form is closed
  useEffect(() => {
    if (!isOpen) {
      setContent("");
    }
  }, [isOpen]);

  const handleContentChange = (value: string) => {
    // Limit input to maximum character count
    if (value.length <= MAX_MEMORY_LENGTH) {
      setContent(value);
    }
  };

  const handleSave = async () => {
    if (!content.trim()) return;

    setIsSaving(true);
    try {
      const response = await memoryApi.createMemory({
        content: content.trim(),
      });

      if (response.success) {
        toast.success("Memory added successfully");
        setContent("");
        onMemoryAdded();
        onClose();
      } else {
        toast.error(response.message || "Failed to add memory");
      }
    } catch (error) {
      console.error("Error adding memory:", error);
      toast.error("Failed to add memory");
    } finally {
      setIsSaving(false);
    }
  };

  // Handle keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Save on Ctrl+Enter or Cmd+Enter
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (content.trim()) {
        handleSave();
      }
    }
    // Close on Escape
    else if (e.key === "Escape") {
      onClose();
    }
  };

  // If not open, don't render anything
  if (!isOpen) return null;

  return (
    <div className="relative mb-4 rounded-2xl border border-zinc-700 p-4">
      <div className="mb-2 flex items-center justify-between">
        <Button
          isIconOnly
          size="sm"
          variant="light"
          onPress={onClose}
          className="absolute top-2 right-2"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="mt-6 flex flex-col gap-2">
        <Textarea
          ref={textareaRef}
          placeholder="Enter a memory to store..."
          value={content}
          onValueChange={handleContentChange}
          onKeyDown={handleKeyDown}
          minRows={4}
          maxRows={6}
          label="Add New Memory"
          description="GAIA will not add the memory if it is unable to extract valuable information from your text. Please add specific and meaningful information about yourself, your preferences, or important details you want GAIA to remember."
          errorMessage={
            content.length > MAX_MEMORY_LENGTH
              ? `Content must be ${MAX_MEMORY_LENGTH} characters or less. Currently ${content.length} characters.`
              : undefined
          }
          isInvalid={content.length > MAX_MEMORY_LENGTH}
          classNames={{
            input: "bg-zinc-800 text-sm",
            inputWrapper: "bg-zinc-800 focus:bg-zinc-700/50",
            description: "text-zinc-400 text-xs",
          }}
          autoFocus
        />
      </div>

      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="flat" onPress={onClose}>
          Cancel
        </Button>
        <Button
          size="sm"
          color="primary"
          onPress={handleSave}
          isDisabled={!content.trim()}
          isLoading={isSaving}
        >
          Save Memory
        </Button>
      </div>
    </div>
  );
}
