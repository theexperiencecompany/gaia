"use client";

import { Dropdown, Menu } from "@heroui/react";
import {
  Delete02Icon,
  MoreVerticalIcon,
  PencilEdit02Icon,
  PinIcon,
  StarIcon,
} from "@icons";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";

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
      <GaiaButton
        className="w-full justify-start text-sm font-light"
        size="sm"
        variant={active ? "tertiary" : "ghost"}
        tone={active ? "dim" : "muted"}
      >
        <span className="truncate">{label}</span>
      </GaiaButton>

      {/* Always-rendered dropdown trigger — fades in on hover like real ChatOptionsDropdown */}
      <div className="absolute right-0">
        <Dropdown>
          <GaiaButton
            isIconOnly
            size="sm"
            variant="ghost"
            tone="muted"
            className={`shrink-0 ${buttonHovered ? "backdrop-blur-lg" : ""}`}
            aria-label="Chat options"
          >
            <MoreVerticalIcon
              width={16}
              height={16}
              className={`transition-all ${buttonHovered ? "opacity-100" : "opacity-0"}`}
            />
          </GaiaButton>
          <Dropdown.Popover
            placement="right top"
            className="dark w-fit min-w-fit"
          >
            <Menu aria-label="Chat actions">
              <Menu.Item
                id="star"
                textValue="Star"
                className={toneVariants({ tone: "muted" })}
              >
                <StarIcon className="h-[15px] w-[15px]" />
                Star
              </Menu.Item>
              <Menu.Item
                id="rename"
                textValue="Rename"
                className={toneVariants({ tone: "muted" })}
              >
                <PencilEdit02Icon className="h-[15px] w-[15px]" />
                Rename
              </Menu.Item>
              <Menu.Item
                id="pin"
                textValue="Pin"
                className={toneVariants({ tone: "muted" })}
              >
                <PinIcon className="h-[15px] w-[15px]" />
                Pin
              </Menu.Item>
              <Menu.Item id="delete" textValue="Delete" variant="danger">
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
