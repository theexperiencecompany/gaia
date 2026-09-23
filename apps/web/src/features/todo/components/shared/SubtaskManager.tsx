"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Input } from "@heroui/input";
import { Cancel01Icon, PlusSignIcon, Tick02Icon } from "@icons";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { SubTask } from "@/types/features/todoTypes";

interface SubtaskManagerProps {
  subtasks: SubTask[];
  onSubtasksChange: (subtasks: SubTask[]) => void;
  className?: string;
}

export default function SubtaskManager({
  subtasks,
  onSubtasksChange,
  className,
}: SubtaskManagerProps) {
  const [newSubtaskTitle, setNewSubtaskTitle] = useState("");
  const [editingSubtaskId, setEditingSubtaskId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const handleAddSubtask = () => {
    if (!newSubtaskTitle.trim()) return;

    const newSubtask: SubTask = {
      id: Date.now().toString(),
      title: newSubtaskTitle.trim(),
      completed: false,
      created_at: new Date().toISOString(),
    };

    onSubtasksChange([...subtasks, newSubtask]);
    setNewSubtaskTitle("");
  };

  const handleToggleSubtask = (subtaskId: string) => {
    const updatedSubtasks = subtasks.map((subtask) =>
      subtask.id === subtaskId
        ? { ...subtask, completed: !subtask.completed }
        : subtask,
    );
    onSubtasksChange(updatedSubtasks);
  };

  const handleDeleteSubtask = (subtaskId: string) => {
    const updatedSubtasks = subtasks.filter(
      (subtask) => subtask.id !== subtaskId,
    );
    onSubtasksChange(updatedSubtasks);
  };

  const handleStartEdit = (subtask: SubTask) => {
    setEditingSubtaskId(subtask.id);
    setEditingTitle(subtask.title);
  };

  const handleSaveEdit = () => {
    if (!editingTitle.trim() || !editingSubtaskId) return;

    const updatedSubtasks = subtasks.map((subtask) =>
      subtask.id === editingSubtaskId
        ? { ...subtask, title: editingTitle.trim() }
        : subtask,
    );
    onSubtasksChange(updatedSubtasks);
    setEditingSubtaskId(null);
    setEditingTitle("");
  };

  const handleCancelEdit = () => {
    setEditingSubtaskId(null);
    setEditingTitle("");
  };

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLInputElement>,
    action: "add" | "edit",
  ) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (action === "add") {
        handleAddSubtask();
      } else {
        handleSaveEdit();
      }
    } else if (e.key === "Escape" && action === "edit") {
      handleCancelEdit();
    }
  };

  return (
    <div className={cn("space-y-3", className)}>
      {/* Subtasks Header */}
      {subtasks.length > 0 && (
        <div className="flex items-center justify-between text-sm text-zinc-500">
          <span>Subtasks</span>
          <span>
            {" "}
            ({subtasks.filter((s) => s.completed).length}/{subtasks.length})
          </span>
        </div>
      )}

      {/* Add New Subtask */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Input
            placeholder="Add a subtask..."
            value={newSubtaskTitle}
            onValueChange={setNewSubtaskTitle}
            onKeyDown={(e) => handleKeyDown(e, "add")}
            variant="flat"
            size="md"
            classNames={{
              inputWrapper: "h-9 min-h-9",
              input: "text-sm text-zinc-200 placeholder:text-zinc-500",
            }}
          />
        </div>
        <Button
          size="sm"
          isIconOnly
          radius="sm"
          variant="flat"
          onPress={handleAddSubtask}
          isDisabled={!newSubtaskTitle.trim()}
          className={`h-9 w-9 ${!newSubtaskTitle.trim() ? "text-zinc-600" : "text-zinc-200"}`}
        >
          <PlusSignIcon size={16} />
        </Button>
      </div>

      {/* Existing Subtasks */}
      {subtasks.length > 0 && (
        <div className="space-y-2">
          {subtasks.map((subtask) => (
            <div
              key={subtask.id}
              className="group hover:bg-zinc-800/50 flex items-center gap-2 rounded-xl transition-colors p-2"
            >
              <div className="shrink-0">
                <Checkbox
                  isSelected={subtask.completed}
                  onChange={() => handleToggleSubtask(subtask.id)}
                  radius="full"
                  color="success"
                />
              </div>

              {editingSubtaskId === subtask.id ? (
                <div className="flex flex-1 gap-2">
                  <Input
                    value={editingTitle}
                    onValueChange={setEditingTitle}
                    onKeyDown={(e) => handleKeyDown(e, "edit")}
                    variant="flat"
                    size="sm"
                    classNames={{
                      base: "flex-1",
                      inputWrapper: "h-7 min-h-7",
                      input: "text-sm text-zinc-200",
                    }}
                    autoFocus
                  />
                  <Button
                    size="sm"
                    isIconOnly
                    radius="sm"
                    variant="light"
                    onPress={handleSaveEdit}
                    isDisabled={!editingTitle.trim()}
                    className="h-7 w-7 text-zinc-400 hover:text-zinc-200"
                  >
                    <Tick02Icon />
                  </Button>
                  <Button
                    size="sm"
                    isIconOnly
                    radius="sm"
                    variant="light"
                    onPress={handleCancelEdit}
                    className="h-7 w-7 text-zinc-400 hover:text-zinc-200"
                  >
                    <Cancel01Icon size={12} />
                  </Button>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => handleStartEdit(subtask)}
                    className={cn(
                      "flex-1 cursor-pointer p-0 text-left text-sm text-zinc-200 select-none",
                      subtask.completed && "text-zinc-500 line-through",
                    )}
                  >
                    {subtask.title}
                  </button>
                  <Button
                    size="sm"
                    isIconOnly
                    radius="sm"
                    variant="light"
                    onPress={() => handleDeleteSubtask(subtask.id)}
                    className="h-7 w-7 text-zinc-500 opacity-0 group-hover:opacity-100 hover:text-red-400"
                  >
                    <Cancel01Icon size={14} />
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
