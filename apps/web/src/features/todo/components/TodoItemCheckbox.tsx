import { Checkbox, type CheckboxProps } from "@heroui/checkbox";
import type { ChangeEvent } from "react";
import { Priority } from "@/types/features/todoTypes";

interface TodoItemCheckboxProps {
  completed: boolean;
  priority: Priority;
  color: CheckboxProps["color"];
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}

/** An open todo's checkbox is a dashed ring in its priority color. */
export function TodoItemCheckbox({
  completed,
  priority,
  color,
  onChange,
}: TodoItemCheckboxProps) {
  return (
    <Checkbox
      isSelected={completed}
      onChange={onChange}
      color={color}
      radius="full"
      classNames={{
        wrapper: completed
          ? "mt-1"
          : priority === Priority.HIGH
            ? "mt-1 border-red-500 border-dashed! border-1 before:border-0! bg-zinc-900"
            : priority === Priority.MEDIUM
              ? "mt-1 border-yellow-500 border-dashed! border-1 before:border-0! bg-zinc-900"
              : priority === Priority.LOW
                ? "mt-1 border-blue-500 border-dashed! border-1 before:border-0! bg-zinc-900"
                : "mt-1 border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-900",
        label: "w-[30vw]",
      }}
    />
  );
}
