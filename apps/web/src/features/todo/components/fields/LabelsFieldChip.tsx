"use client";

import { Input } from "@heroui/react";
import { Cancel01Icon, PlusSignIcon, Tag01Icon } from "@icons";
import { useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import BaseFieldChip from "./BaseFieldChip";
import FieldChipOption from "./FieldChipOption";

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

  const trimmedLabel = newLabel.trim();
  const canAddLabel = trimmedLabel !== "" && !value.includes(trimmedLabel);

  const handleAddLabel = () => {
    if (canAddLabel) {
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
          <div className="border-0 bg-zinc-900 p-3">
            {/* Add new label */}
            <div className="mb-1">
              <div className="flex gap-2">
                <div className="relative flex-1 mb-3">
                  <Input
                    placeholder="Add label..."
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.nativeEvent.isComposing) return;
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddLabel();
                        onClose();
                      }
                    }}
                    aria-label="Add new label"
                    className={inputVariants({
                      size: "sm",
                      className: toneVariants({
                        tone: "bright",
                        className:
                          "border-0 text-sm hover:bg-zinc-700 focus:bg-zinc-700",
                      }),
                    })}
                  />
                </div>
                <GaiaButton
                  aria-label="Add label"
                  size="sm"
                  variant="tertiary"
                  tone={canAddLabel ? "bright" : "subtle"}
                  isIconOnly
                  isDisabled={!canAddLabel}
                  onPress={() => {
                    handleAddLabel();
                    onClose();
                  }}
                >
                  <PlusSignIcon size={14} />
                </GaiaButton>
              </div>
            </div>

            {/* Existing labels */}
            {value.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {value.map((label) => (
                  <div
                    key={label}
                    className="flex items-center gap-1 rounded-md bg-zinc-800 px-2 py-1 text-sm text-zinc-400 hover:bg-zinc-700"
                  >
                    <Tag01Icon size={12} />
                    {label}
                    <GaiaButton
                      aria-label="Remove label"
                      variant="ghost"
                      tone="muted"
                      hoverTone="bright"
                      size="sm"
                      isIconOnly
                      onPress={() => handleRemoveLabel(label)}
                      className="h-4 w-4 min-w-4"
                    >
                      <Cancel01Icon size={10} />
                    </GaiaButton>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick actions */}
          {value.length > 0 && (
            <>
              <div className="my-1 h-px bg-zinc-700" />
              <FieldChipOption
                onSelect={() => {
                  onChange([]);
                  onClose();
                }}
                className="gap-2 rounded-md text-red-400"
              >
                <Cancel01Icon size={14} />
                Clear all labels
              </FieldChipOption>
            </>
          )}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-zinc-500">
              Type{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">#label</span>{" "}
              in title/description to add labels
            </p>
          </div>
        </div>
      )}
    </BaseFieldChip>
  );
}
