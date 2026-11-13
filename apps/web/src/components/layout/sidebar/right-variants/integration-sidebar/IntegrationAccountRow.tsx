"use client";

import {
  Chip,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/react";
import {
  Delete02Icon,
  MoreHorizontalIcon,
  PencilEdit02Icon,
  RefreshIcon,
  StarIcon,
} from "@icons";
import type { IntegrationAccountResponse } from "@shared/api/generated";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface IntegrationAccountRowProps {
  account: IntegrationAccountResponse;
  isPending: boolean;
  onMakePrimary: () => void;
  onRename: () => void;
  onReconnect: () => void;
  onRemove: () => void;
}

/** One connected account: who it is, whether it is the default, and what can be done to it. */
export function IntegrationAccountRow({
  account,
  isPending,
  onMakePrimary,
  onRename,
  onReconnect,
  onRemove,
}: IntegrationAccountRowProps) {
  const isExpired = account.status === "expired";

  return (
    <div className="flex items-center gap-2 rounded-2xl bg-zinc-800 px-3 py-2">
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm text-zinc-200">
          {account.displayName}
        </span>
        {account.nickname && (
          <span className="truncate text-xs text-zinc-500">
            {account.label}
          </span>
        )}
      </div>
      {account.isPrimary && (
        <Chip size="sm" variant="soft" color="accent">
          Primary
        </Chip>
      )}
      {isExpired && (
        <Chip size="sm" variant="soft" color="warning">
          Expired
        </Chip>
      )}
      <Dropdown>
        <DropdownTrigger>
          <GaiaButton
            isIconOnly
            size="sm"
            variant="ghost"
            isPending={isPending}
            aria-label={`Manage ${account.displayName}`}
          >
            <MoreHorizontalIcon className="size-4" />
          </GaiaButton>
        </DropdownTrigger>
        <Dropdown.Popover placement="bottom end">
          <DropdownMenu
            aria-label={`Actions for ${account.displayName}`}
            disabledKeys={account.isPrimary || isExpired ? ["primary"] : []}
          >
            {isExpired ? (
              <DropdownItem
                id="reconnect"
                key="reconnect"
                textValue="Reconnect"
                onAction={onReconnect}
              >
                <RefreshIcon className="size-4" />
                Reconnect
              </DropdownItem>
            ) : (
              <DropdownItem
                id="primary"
                key="primary"
                textValue="Make primary"
                onAction={onMakePrimary}
              >
                <StarIcon className="size-4" />
                Make primary
              </DropdownItem>
            )}
            <DropdownItem
              id="rename"
              key="rename"
              textValue="Rename"
              onAction={onRename}
            >
              <PencilEdit02Icon className="size-4" />
              Rename
            </DropdownItem>
            <DropdownItem
              id="remove"
              key="remove"
              textValue="Disconnect"
              variant="danger"
              onAction={onRemove}
            >
              <Delete02Icon className="size-4" />
              Disconnect
            </DropdownItem>
          </DropdownMenu>
        </Dropdown.Popover>
      </Dropdown>
    </div>
  );
}
