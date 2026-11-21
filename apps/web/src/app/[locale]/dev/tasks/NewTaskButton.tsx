"use client";

import { Dropdown } from "@heroui/react";
import { PlusSignIcon, UserIcon } from "@icons";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { GaiaMark } from "./TaskIconTile";
import type { Assignee } from "./taskModel";

const NEW_FOR: {
  id: Assignee;
  label: string;
  description: string;
}[] = [
  { id: "you", label: "For me", description: "A to-do you'll do yourself" },
  { id: "gaia", label: "For GAIA", description: "Hand something to GAIA" },
];

/** The one question creating a task asks: who it's for. Everything else comes after. */
export default function NewTaskButton({
  onPick,
}: {
  onPick: (assignee: Assignee) => void;
}) {
  return (
    <Dropdown>
      <GaiaButton size="sm" variant="tertiary" tone="strong">
        <PlusSignIcon className="size-4" />
        New task
      </GaiaButton>
      <Dropdown.Popover
        placement="bottom end"
        offset={7}
        className={shapeVariants({ shape: "lg" })}
      >
        <Dropdown.Menu
          aria-label="Who is the task for"
          onAction={(key) => {
            const picked = NEW_FOR.find((item) => item.id === key);
            if (picked) onPick(picked.id);
          }}
        >
          {NEW_FOR.map((item) => (
            <Dropdown.Item
              key={item.id}
              id={item.id}
              textValue={item.label}
              className="gap-2"
            >
              <span aria-hidden className="flex shrink-0">
                {item.id === "you" ? (
                  <UserIcon className="size-5 text-zinc-400" />
                ) : (
                  <GaiaMark size={20} />
                )}
              </span>
              <div className="flex flex-col">
                <span>{item.label}</span>
                <span className="text-xs text-zinc-400">
                  {item.description}
                </span>
              </div>
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
