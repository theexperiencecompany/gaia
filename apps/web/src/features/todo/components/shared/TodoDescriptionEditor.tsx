"use client";

import { Textarea } from "@heroui/input";
import type React from "react";
import { useState } from "react";
import type { Todo, TodoUpdate } from "@/types/features/todoTypes";

interface TodoDescriptionEditorProps {
  todo: Todo;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
}

/**
 * The sidebar's inline-editable todo description — click to edit, blur to
 * save, Escape to cancel.
 */
export const TodoDescriptionEditor: React.FC<TodoDescriptionEditorProps> = ({
  todo,
  onUpdate,
}) => {
  const [isEditing, setIsEditing] = useState(false);

  const save = (newDescription: string) => {
    if (newDescription !== todo.description) {
      onUpdate(todo.id, { description: newDescription });
    }
    setIsEditing(false);
  };

  if (isEditing) {
    return (
      <Textarea
        defaultValue={todo.description || ""}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setIsEditing(false);
          }
        }}
        onBlur={(e) => save(e.target.value)}
        placeholder="Add a description..."
        minRows={4}
        maxRows={6}
        autoFocus
        classNames={{
          input: "bg-transparent text-zinc-200 placeholder:text-zinc-500",
          inputWrapper:
            "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
        }}
        variant="flat"
      />
    );
  }

  return (
    <p
      className={`text-sm leading-relaxed ${todo.completed ? "text-zinc-600" : "text-zinc-400"}`}
    >
      <button
        type="button"
        onClick={() => setIsEditing(true)}
        className="w-full cursor-pointer text-left transition-colors hover:text-zinc-300"
      >
        {todo.description || "Add a description..."}
      </button>
    </p>
  );
};
