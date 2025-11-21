"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";

import { CheckCircle, MoreHorizontal, Plus, Trash2 } from "@/icons";

interface TodoHeaderProps {
  title: string;
  todoCount: number;
  selectedCount?: number;
  allSelected?: boolean;
  onSelectAll?: () => void;
  onBulkComplete?: () => void;
  onBulkDelete?: () => void;
  onAddTodo?: () => void;
}

export default function TodoHeader({
  title,
  todoCount,
  selectedCount,
  allSelected,
  onSelectAll,
  onBulkComplete,
  onBulkDelete,
  onAddTodo,
}: TodoHeaderProps) {
  const showBulkActions =
    selectedCount !== undefined &&
    onSelectAll &&
    onBulkComplete &&
    onBulkDelete;
  const hasSelection = selectedCount !== undefined && selectedCount > 0;

  return (
    <div className="border-b border-default-200 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {todoCount > 0 && showBulkActions && (
            <Checkbox
              isSelected={allSelected || false}
              isIndeterminate={hasSelection && selectedCount < todoCount}
              onChange={onSelectAll}
              size="sm"
            />
          )}
          <div>
            <h1 className="text-lg font-semibold">{title}</h1>
            <p className="text-sm text-foreground-500">
              {todoCount} {todoCount === 1 ? "task" : "tasks"}
              {hasSelection && ` • ${selectedCount} selected`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {hasSelection && showBulkActions ? (
            <>
              <Button
                size="sm"
                variant="flat"
                startContent={<CheckCircle className="h-4 w-4" />}
                onPress={onBulkComplete}
              >
                Complete
              </Button>
              <Button
                size="sm"
                variant="flat"
                color="danger"
                startContent={<Trash2 className="h-4 w-4" />}
                onPress={onBulkDelete}
              >
                Delete
              </Button>
              <Dropdown>
                <DropdownTrigger>
                  <Button isIconOnly size="sm" variant="flat">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownTrigger>
                <DropdownMenu aria-label="Bulk actions">
                  <DropdownItem key="move">Move to project...</DropdownItem>
                  <DropdownItem key="priority">Set priority...</DropdownItem>
                  <DropdownItem key="labels">Add labels...</DropdownItem>
                </DropdownMenu>
              </Dropdown>
            </>
          ) : (
            onAddTodo && (
              <Button
                isIconOnly
                size="sm"
                variant="flat"
                onPress={onAddTodo}
                className="text-primary"
              >
                <Plus className="h-4 w-4" />
              </Button>
            )
          )}
        </div>
      </div>
    </div>
  );
}
