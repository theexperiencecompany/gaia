"use client";

import { Checkbox, Input, TextArea } from "@heroui/react";
import { useState } from "react";

interface TodoSidebarTitleProps {
  title: string;
  completed: boolean;
  onToggleComplete: () => void;
  onSave: (title: string) => void;
}

export function TodoSidebarTitle({
  title,
  completed,
  onToggleComplete,
  onSave,
}: TodoSidebarTitleProps) {
  const [isEditing, setIsEditing] = useState(false);
  const save = (value: string) => {
    onSave(value);
    setIsEditing(false);
  };

  return (
    <div className="flex items-start gap-1">
      <Checkbox
        isSelected={completed}
        onChange={onToggleComplete}
        className={`mt-1 ${completed ? "" : "border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-900 "}`}
      >
        <Checkbox.Content className="w-[30vw]">
          <Checkbox.Control>
            <Checkbox.Indicator />
          </Checkbox.Control>
        </Checkbox.Content>
      </Checkbox>
      <div className="flex-1 space-y-3">
        {isEditing ? (
          <Input
            defaultValue={title}
            onKeyDown={(e) => {
              // Don't commit while an IME composition is active (CJK
              // users press Enter to confirm candidates).
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter") {
                save(e.currentTarget.value);
              }
              if (e.key === "Escape") {
                setIsEditing(false);
              }
            }}
            onBlur={(e) => save(e.target.value)}
            autoFocus
            className="border-0 bg-transparent text-2xl font-medium text-zinc-100 shadow-none placeholder:text-zinc-500 hover:bg-transparent focus:bg-transparent"
          />
        ) : (
          <h1
            style={{ wordBreak: "break-all" }}
            className={`text-2xl leading-tight font-medium ${completed ? "text-zinc-500 line-through" : "text-zinc-100"}`}
          >
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              className="w-full cursor-pointer text-left transition-colors hover:text-zinc-200"
            >
              {title}
            </button>
          </h1>
        )}
      </div>
    </div>
  );
}

interface TodoSidebarDescriptionProps {
  description: string | null | undefined;
  completed: boolean;
  onSave: (description: string) => void;
}

export function TodoSidebarDescription({
  description,
  completed,
  onSave,
}: TodoSidebarDescriptionProps) {
  const [isEditing, setIsEditing] = useState(false);

  if (isEditing) {
    return (
      <TextArea
        defaultValue={description || ""}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setIsEditing(false);
          }
        }}
        onBlur={(e) => {
          onSave(e.target.value);
          setIsEditing(false);
        }}
        placeholder="Add a description..."
        rows={4}
        autoFocus
        className="max-h-40 bg-zinc-800/30 text-zinc-200 shadow-none placeholder:text-zinc-500 hover:bg-zinc-800/50"
      />
    );
  }

  return (
    <p
      className={`text-sm leading-relaxed ${completed ? "text-zinc-600" : "text-zinc-400"}`}
    >
      <button
        type="button"
        onClick={() => setIsEditing(true)}
        className="w-full cursor-pointer text-left transition-colors hover:text-zinc-300"
      >
        {description || "Add a description..."}
      </button>
    </p>
  );
}
