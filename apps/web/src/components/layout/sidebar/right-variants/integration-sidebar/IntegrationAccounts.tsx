"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { PlusSignIcon } from "@icons";
import type { IntegrationAccountResponse } from "@shared/api/generated";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useIntegrationAccounts } from "@/features/integrations/hooks/useIntegrationAccounts";
import type { Integration } from "@/features/integrations/types";

import { IntegrationAccountRenameModal } from "./IntegrationAccountRenameModal";
import { IntegrationAccountRow } from "./IntegrationAccountRow";

interface IntegrationAccountsProps {
  integration: Integration;
  /** Starts a connect; a new identity is added, a known one is re-authorized in place. */
  onConnect: (integrationId: string) => Promise<unknown>;
}

/** The accounts connected to a Composio integration, the primary first among equals. */
export function IntegrationAccounts({
  integration,
  onConnect,
}: IntegrationAccountsProps) {
  const {
    accounts,
    maxAccounts,
    isLoading,
    pendingAccountId,
    makePrimary,
    rename,
    remove,
  } = useIntegrationAccounts(integration.id);
  const [removing, setRemoving] = useState<IntegrationAccountResponse | null>(
    null,
  );
  const [renaming, setRenaming] = useState<IntegrationAccountResponse | null>(
    null,
  );
  const [isAdding, setIsAdding] = useState(false);

  const addAccount = async () => {
    setIsAdding(true);
    try {
      await onConnect(integration.id);
    } finally {
      setIsAdding(false);
    }
  };

  if (isLoading) {
    return <Skeleton className="mt-3 h-12 w-full rounded-2xl" />;
  }
  if (accounts.length === 0) return null;

  const atLimit = accounts.length >= maxAccounts;

  return (
    <div className="mt-3 flex flex-col gap-2">
      <h2 className="text-sm font-medium text-zinc-300">Accounts</h2>
      {accounts.map((account) => (
        <IntegrationAccountRow
          key={account.id}
          account={account}
          isPending={pendingAccountId === account.id}
          onMakePrimary={() => makePrimary(account.id)}
          onRename={() => setRenaming(account)}
          onReconnect={() => onConnect(integration.id)}
          onRemove={() => setRemoving(account)}
        />
      ))}
      <Button
        size="sm"
        variant="flat"
        startContent={<PlusSignIcon className="size-4" />}
        isLoading={isAdding}
        isDisabled={atLimit}
        onPress={addAccount}
      >
        {atLimit
          ? `${maxAccounts} accounts connected (the maximum)`
          : "Add another account"}
      </Button>

      <IntegrationAccountRenameModal
        key={renaming?.id ?? "closed"}
        account={renaming}
        onSave={rename}
        onClose={() => setRenaming(null)}
      />

      <ConfirmationDialog
        isOpen={removing !== null}
        title="Disconnect account"
        message={
          accounts.length === 1
            ? `Disconnect ${removing?.displayName}? It is your only ${integration.name} account, so ${integration.name} will be disconnected.`
            : `Disconnect ${removing?.displayName}? GAIA will stop using this ${integration.name} account.`
        }
        confirmText="Disconnect"
        cancelText="Cancel"
        variant="destructive"
        onConfirm={() => {
          if (removing) remove(removing.id);
          setRemoving(null);
        }}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
