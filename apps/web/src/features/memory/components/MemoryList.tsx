"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import {
  AiBrain01Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  PlusSignIcon,
  Search01Icon,
} from "@icons";
import { useCallback, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { AddMemoryModal } from "@/features/memory/components/AddMemoryModal";
import { EditMemoryModal } from "@/features/memory/components/EditMemoryModal";
import { MemoryEmptyState } from "@/features/memory/components/MemoryEmptyState";
import { MemoryRow } from "@/features/memory/components/MemoryRow";
import { useMemoryActions } from "@/features/memory/hooks/useMemoryActions";
import { useMemoryListData } from "@/features/memory/hooks/useMemoryListData";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";

interface MemoryListProps {
  onChanged: () => void;
}

type Confirm = ReturnType<typeof useConfirmation>["confirm"];

/** Two confirmations: the count, then the irreversibility. */
async function confirmClearAll(confirm: Confirm, total: number) {
  const confirmed = await confirm({
    title: "Clear all memories",
    message: `Permanently delete all ${total} memories? GAIA will forget everything it has learned about you.`,
    confirmText: "Continue",
    cancelText: "Cancel",
    variant: "destructive",
  });
  if (!confirmed) return false;
  return confirm({
    title: "This cannot be undone",
    message:
      "Your folders, journal, and learned facts will be erased for good. Really clear everything?",
    confirmText: "Clear everything",
    cancelText: "Keep my memories",
    variant: "destructive",
  });
}

export function MemoryList({ onChanged }: MemoryListProps) {
  const list = useMemoryListData();
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const { confirm, confirmationProps } = useConfirmation();

  const handleChanged = useCallback(() => {
    list.refresh();
    onChanged();
  }, [list.refresh, onChanged]);

  const actions = useMemoryActions(handleChanged);

  const handleClearAll = useCallback(async () => {
    const confirmed = await confirmClearAll(confirm, list.totalCount);
    if (!confirmed) return;

    setIsClearing(true);
    try {
      const response = await memoryApi.deleteAllMemories();
      if (response.success) {
        toast.success(response.message || "All memories cleared");
        list.setPage(1);
        handleChanged();
      } else {
        toast.error(response.message || "Failed to clear memories");
      }
    } catch {
      toast.error("Failed to clear memories");
    } finally {
      setIsClearing(false);
    }
  }, [confirm, list.totalCount, list.setPage, handleChanged]);

  const { isSearching, memories, totalCount, totalPages, page } = list;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Input
          size="sm"
          variant="flat"
          radius="lg"
          placeholder="Search memories"
          value={list.query}
          onValueChange={list.setQuery}
          startContent={<Search01Icon className="size-4 text-zinc-500" />}
          className="max-w-xs"
          isClearable
        />
        <div className="flex-1" />
        {totalCount > 0 && (
          <Button
            size="sm"
            color="danger"
            variant="flat"
            className="rounded-xl"
            isLoading={isClearing}
            onPress={handleClearAll}
          >
            Clear all
          </Button>
        )}
        <Button
          size="sm"
          color="primary"
          className="rounded-xl"
          startContent={<PlusSignIcon className="size-4" />}
          onPress={() => setIsAddModalOpen(true)}
        >
          Add memory
        </Button>
      </div>

      {list.loading ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full rounded-2xl" />
          <Skeleton className="h-14 w-full rounded-2xl" />
          <Skeleton className="h-14 w-full rounded-2xl" />
        </div>
      ) : memories.length === 0 ? (
        <MemoryEmptyState
          icon={AiBrain01Icon}
          title={
            isSearching ? "No memories match your search" : "No memories yet"
          }
          description={
            isSearching
              ? undefined
              : "Start a conversation and GAIA will remember the important details"
          }
        />
      ) : (
        <div className="overflow-hidden rounded-2xl bg-zinc-800 py-1">
          {memories.map((memory) => (
            <MemoryRow
              key={memory.id}
              memory={memory}
              showCategory
              isDeleting={actions.deletingId === memory.id}
              onEdit={actions.setEditingMemory}
              onForget={async (target) => {
                // Pop the row immediately on success; the refetch then settles
                // counts and pagination.
                if (await actions.forgetMemory(target)) {
                  list.removeLocally(target.id);
                }
              }}
            />
          ))}
        </div>
      )}

      {!isSearching && totalPages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-xs text-zinc-500">
            Page {page} of {totalPages}
          </span>
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            className="rounded-xl"
            aria-label="Previous page"
            isDisabled={page <= 1}
            onPress={() => list.setPage(page - 1)}
          >
            <ArrowLeft01Icon className="size-4" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            className="rounded-xl"
            aria-label="Next page"
            isDisabled={page >= totalPages}
            onPress={() => list.setPage(page + 1)}
          >
            <ArrowRight01Icon className="size-4" />
          </Button>
        </div>
      )}

      <AddMemoryModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onMemoryAdded={handleChanged}
      />
      <EditMemoryModal
        memory={actions.editingMemory}
        onClose={() => actions.setEditingMemory(null)}
        onSaved={handleChanged}
      />
      <ConfirmationDialog {...actions.confirmationProps} />
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
}
