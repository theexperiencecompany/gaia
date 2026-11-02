"use client";

import { Button, Dropdown, Menu } from "@heroui/react";
import {
  Delete02Icon,
  MoreVerticalIcon,
  PencilEdit02Icon,
  PinIcon,
  StarIcon,
} from "@icons";
import { useState } from "react";

interface DemoChatTabProps {
  label: string;
  active?: boolean;
}

// Mirrors real ChatTab — always-rendered 3-dot button that fades in on hover
export default function DemoChatTab({ label, active }: DemoChatTabProps) {
  const [buttonHovered, setButtonHovered] = useState(false);

  return (
    <div
      className="relative z-0 flex"
      onMouseOut={() => setButtonHovered(false)}
      onMouseOver={() => setButtonHovered(true)}
      onFocus={() => setButtonHovered(true)}
      onBlur={() => setButtonHovered(false)}
    >
      <Button
        className={`w-full justify-start px-2 text-sm font-light ${active ? "text-zinc-300" : "text-zinc-400 hover:text-zinc-300"}`}
        size="sm"
        variant={active ? "tertiary" : "ghost"}
      >
        <span className="truncate">{label}</span>
      </Button>

      {/* Always-rendered dropdown trigger — fades in on hover like real ChatOptionsDropdown */}
      <div className="absolute right-0">
        <Dropdown>
          <Dropdown.Trigger
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border-0 bg-transparent p-0 text-zinc-400 hover:bg-zinc-700 hover:text-white ${buttonHovered ? "backdrop-blur-lg" : ""}`}
            onClick={(e) => e.stopPropagation()}
            aria-label="Chat options"
          >
            <MoreVerticalIcon
              width={16}
              height={16}
              className={`transition-all ${buttonHovered ? "opacity-100" : "opacity-0"}`}
            />
          </Dropdown.Trigger>
          <Dropdown.Popover
            placement="right top"
            className="dark w-fit min-w-fit text-foreground"
          >
            <Menu aria-label="Chat actions">
              <Menu.Item id="star" textValue="Star" className="text-zinc-400">
                <StarIcon className="h-[15px] w-[15px]" />
                Star
              </Menu.Item>
              <Menu.Item
                id="rename"
                textValue="Rename"
                className="text-zinc-400"
              >
                <PencilEdit02Icon className="h-[15px] w-[15px]" />
                Rename
              </Menu.Item>
              <Menu.Item id="pin" textValue="Pin" className="text-zinc-400">
                <PinIcon className="h-[15px] w-[15px]" />
                Pin
              </Menu.Item>
              <Menu.Item
                id="delete"
                textValue="Delete"
                variant="danger"
                className="text-danger"
              >
                <Delete02Icon className="h-[15px] w-[15px]" />
                Delete
              </Menu.Item>
            </Menu>
          </Dropdown.Popover>
        </Dropdown>
      </div>
    </div>
  );
}
