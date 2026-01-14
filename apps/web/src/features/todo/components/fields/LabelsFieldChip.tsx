"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { useState } from "react";

import { Cancel01Icon, PlusSignIcon, Tag01Icon } from "@/icons";

import BaseFieldChip from "./BaseFieldChip";

interface LabelsFieldChipProps {
  value: string[];
  onChange: (labels: string[]) => void;
  className?: string;
}

export default function LabelsFieldChip({
  value = [],
  onChange,
  className,
}: LabelsFieldChipProps) {
  const [newLabel, setNewLabel] = useState("");

  const displayValue =
    value.length > 0
      ? `${value.length} label${value.length > 1 ? "s" : ""}`
      : undefined;

  const handleAddLabel = () => {
    const trimmedLabel = newLabel.trim();
    if (trimmedLabel && !value.includes(trimmedLabel)) {
      onChange([...value, trimmedLabel]);
      setNewLabel("");
    }
  };

  const handleRemoveLabel = (labelToRemove: string) => {
    onChange(value.filter((label) => label !== labelToRemove));
  };

  return (
    <BaseFieldChip
      label="Labels"
      value={displayValue}
      placeholder="Labels"
      icon={<Tag01Icon width={18} height={18} />}
      variant={value.length > 0 ? "primary" : "default"}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          <div className="border-0 bg-surface-100 p-3">
            {/* Add new label */}
            <div className="mb-1">
              <div className="flex gap-2">
                <div className="relative flex-1 mb-3">
                  <Input
                    placeholder="Add label..."
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddLabel();
                        onClose();
                      }
                    }}
                    size="sm"
                    aria-label="Add new label"
                    classNames={{
                      input: "text-sm text-foreground-200 placeholder:text-foreground-500",
                      inputWrapper:
                        "border-0 bg-surface-200 hover:bg-surface-300 focus:bg-surface-300 data-[focus=true]:bg-surface-300",
                    }}
                  />
                </div>
                <Button
                  size="sm"
                  variant="light"
                  isDisabled={
                    !newLabel.trim() || value.includes(newLabel.trim())
                  }
                  onPress={() => {
                    handleAddLabel();
                    onClose();
                  }}
                  className={`h-8 min-w-8 border-0 p-0 ${
                    !newLabel.trim() || value.includes(newLabel.trim())
                      ? "bg-surface-200 text-foreground-600 hover:bg-surface-300"
                      : "bg-surface-200 text-foreground-200 hover:bg-surface-300"
                  }`}
                >
                  <PlusSignIcon size={14} />
                </Button>
              </div>
            </div>

            {/* Existing labels */}
            {value.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {value.map((label) => (
                  <div
                    key={label}
                    className="flex items-center gap-1 rounded-md bg-surface-200 px-2 py-1 text-sm text-foreground-400 hover:bg-surface-300"
                  >
                    <Tag01Icon size={12} />
                    {label}
                    <Button
                      variant="light"
                      size="sm"
                      onPress={() => handleRemoveLabel(label)}
                      className="h-4 w-4 min-w-4 border-0 p-0 text-foreground-400 hover:text-foreground-200"
                    >
                      <Cancel01Icon size={10} />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick actions */}
          {value.length > 0 && (
            <>
              <div className="my-1 h-px bg-surface-300" />
              <div
                onClick={() => {
                  onChange([]);
                  onClose();
                }}
                className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-red-400 transition-colors hover:bg-surface-200"
              >
                <Cancel01Icon size={14} />
                Clear all labels
              </div>
            </>
          )}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-foreground-500">
              Type{" "}
              <span className="rounded bg-surface-200 px-1 font-mono">#label</span>{" "}
              in title/description to add labels
            </p>
          </div>
        </div>
      )}
    </BaseFieldChip>
  );
}
