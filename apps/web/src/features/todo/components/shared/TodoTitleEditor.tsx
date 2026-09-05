"use client";

import { Input } from "@heroui/input";
import type React from "react";
import { useState } from "react";
import { GaiaTodoMeta } from "@/features/todo/components/shared/GaiaTodoMeta";
import type { Todo, TodoUpdate } from "@/types/features/todoTypes";

interface TodoTitleEditorProps {
  todo: Todo;
  isGaiaTodo: boolean;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
}

/**
 * The sidebar's inline-editable todo title — click to edit, Enter/blur to
 * save, Escape to cancel — plus the GAIA "because" meta line for GAIA-owned
 * todos.
 */
export const TodoTitleEditor: React.FC<TodoTitleEditorProps> = ({
  todo,
  isGaiaTodo,
  onUpdate,
}) => {
  const [isEditing, setIsEditing] = useState(false);

  const save = (newTitle: string) => {
    if (newTitle.trim() && newTitle !== todo.title) {
      onUpdate(todo.id, { title: newTitle.trim() });
    }
    setIsEditing(false);
  };

  return (
    <div className="flex-1 space-y-3">
      {isEditing ? (
        <Input
          defaultValue={todo.title}
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
          classNames={{
            input:
              "text-2xl font-medium bg-transparent text-zinc-100 placeholder:text-zinc-500",
            inputWrapper:
              "bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
          }}
          variant="underlined"
        />
      ) : (
        <h1
          style={{ wordBreak: "break-all" }}
          className={`text-2xl leading-tight font-medium ${todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"}`}
        >
          <button
            type="button"
            onClick={() => setIsEditing(true)}
            className="w-full cursor-pointer text-left transition-colors hover:text-zinc-200"
          >
            {todo.title}
          </button>
        </h1>
      )}
      {isGaiaTodo && (
        <GaiaTodoMeta
          // A goal's `serves` restates its own title ("raising a pre-seed
          // round" on "Raise a pre-seed round"), so it reads as circular —
          // only tasks carry a meaningful "because".
          serves={todo.kind === "goal" ? null : todo.serves}
          errorMessage={
            todo.execution_status === "failed" ? todo.error_message : null
          }
          todoId={todo.id}
        />
      )}
    </div>
  );
};
