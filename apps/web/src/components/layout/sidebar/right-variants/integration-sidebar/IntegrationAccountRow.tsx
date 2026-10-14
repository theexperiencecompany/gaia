"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import {
  Delete02Icon,
  MoreHorizontalIcon,
  PencilEdit02Icon,
  RefreshIcon,
  StarIcon,
} from "@icons";
import type { IntegrationAccountResponse } from "@shared/api/generated";

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
        <Chip size="sm" variant="flat" color="primary">
          Primary
        </Chip>
      )}
      {isExpired && (
        <Chip size="sm" variant="flat" color="warning">
          Expired
        </Chip>
      )}
      <Dropdown placement="bottom-end">
        <DropdownTrigger>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            isLoading={isPending}
            aria-label={`Manage ${account.displayName}`}
          >
            <MoreHorizontalIcon className="size-4" />
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          aria-label={`Actions for ${account.displayName}`}
          disabledKeys={account.isPrimary || isExpired ? ["primary"] : []}
        >
          {isExpired ? (
            <DropdownItem
              key="reconnect"
              startContent={<RefreshIcon className="size-4" />}
              onPress={onReconnect}
            >
              Reconnect
            </DropdownItem>
          ) : (
            <DropdownItem
              key="primary"
              startContent={<StarIcon className="size-4" />}
              onPress={onMakePrimary}
            >
              Make primary
            </DropdownItem>
          )}
          <DropdownItem
            key="rename"
            startContent={<PencilEdit02Icon className="size-4" />}
            onPress={onRename}
          >
            Rename
          </DropdownItem>
          <DropdownItem
            key="remove"
            color="danger"
            className="text-danger"
            startContent={<Delete02Icon className="size-4" />}
            onPress={onRemove}
          >
            Disconnect
          </DropdownItem>
        </DropdownMenu>
      </Dropdown>
    </div>
  );
}
