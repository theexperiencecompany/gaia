"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
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
    >
      <Button
        className={`w-full justify-start px-2 text-sm font-light ${
          active ? "text-zinc-300" : "text-zinc-400 hover:text-zinc-300"
        }`}
        size="sm"
        variant={active ? "flat" : "light"}
      >
        <span className="truncate">{label}</span>
      </Button>

      {/* Always-rendered dropdown trigger — fades in on hover like real ChatOptionsDropdown */}
      <div className="absolute right-0">
        <Dropdown
          className="dark w-fit min-w-fit text-foreground"
          size="sm"
          placement="right-start"
        >
          <DropdownTrigger>
            <button
              type="button"
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-zinc-400 hover:bg-zinc-700 hover:text-white ${
                buttonHovered ? "backdrop-blur-lg" : ""
              }`}
              onClick={(e) => e.stopPropagation()}
              aria-label="Chat options"
            >
              <MoreVerticalIcon
                width={16}
                height={16}
                className={`transition-all ${
                  buttonHovered ? "opacity-100" : "opacity-0"
                }`}
              />
            </button>
          </DropdownTrigger>
          <DropdownMenu aria-label="Chat actions" variant="faded">
            <DropdownItem
              key="star"
              startContent={<StarIcon className="h-[15px] w-[15px]" />}
              className="text-zinc-400"
            >
              Star
            </DropdownItem>
            <DropdownItem
              key="rename"
              startContent={<PencilEdit02Icon className="h-[15px] w-[15px]" />}
              className="text-zinc-400"
            >
              Rename
            </DropdownItem>
            <DropdownItem
              key="pin"
              startContent={<PinIcon className="h-[15px] w-[15px]" />}
              className="text-zinc-400"
            >
              Pin
            </DropdownItem>
            <DropdownItem
              key="delete"
              startContent={<Delete02Icon className="h-[15px] w-[15px]" />}
              color="danger"
              className="text-danger"
            >
              Delete
            </DropdownItem>
          </DropdownMenu>
        </Dropdown>
      </div>
    </div>
  );
}
