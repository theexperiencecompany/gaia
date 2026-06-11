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
import { useCallback, useEffect, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type {
  MemoryEntry,
  MemoryListResponse,
} from "@/features/memory/api/types";
import { AddMemoryModal } from "@/features/memory/components/AddMemoryModal";
import { EditMemoryModal } from "@/features/memory/components/EditMemoryModal";
import { MemoryRow } from "@/features/memory/components/MemoryRow";
import { MEMORY_PAGE_SIZE } from "@/features/memory/constants";
import { useMemoryActions } from "@/features/memory/hooks/useMemoryActions";
import { useConfirmation } from "@/hooks/useConfirmation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

interface MemoryListProps {
  onChanged: () => void;
}

export function MemoryList({ onChanged }: MemoryListProps) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<MemoryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryEntry[] | null>(
    null,
  );
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const { confirm, confirmationProps } = useConfirmation();

  const fetchPage = useCallback(async (pageToLoad: number) => {
    setLoading(true);
    try {
      const response = await memoryApi.listMemories({
        page: pageToLoad,
        pageSize: MEMORY_PAGE_SIZE,
      });
      setData(response);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPage(page);
  }, [fetchPage, page]);

  // Debounced server-side search across all memories, not just the loaded page.
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchResults(null);
      return;
    }
    let active = true;
    const handle = setTimeout(async () => {
      try {
        const result = await memoryApi.searchMemories(trimmed);
        if (active) setSearchResults(result.memories);
      } catch {
        if (active) setSearchResults([]);
      }
    }, 250);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [query]);

  const handleChanged = useCallback(() => {
    fetchPage(page);
    if (query.trim()) {
      memoryApi
        .searchMemories(query.trim())
        .then((result) => setSearchResults(result.memories))
        .catch(() => setSearchResults([]));
    }
    onChanged();
  }, [fetchPage, page, onChanged, query]);

  const actions = useMemoryActions(handleChanged);

  const handleClearAll = useCallback(async () => {
    const total = data?.total_count ?? 0;
    const confirmed = await confirm({
      title: "Clear all memories",
      message: `Permanently delete all ${total} memories? GAIA will forget everything it has learned about you.`,
      confirmText: "Continue",
      cancelText: "Cancel",
      variant: "destructive",
    });
    if (!confirmed) return;

    const doubleConfirmed = await confirm({
      title: "This cannot be undone",
      message:
        "Your folders, journal, and learned facts will be erased for good. Really clear everything?",
      confirmText: "Clear everything",
      cancelText: "Keep my memories",
      variant: "destructive",
    });
    if (!doubleConfirmed) return;

    setIsClearing(true);
    try {
      const response = await memoryApi.deleteAllMemories();
      if (response.success) {
        toast.success(response.message || "All memories cleared");
        trackEvent(ANALYTICS_EVENTS.MEMORY_CLEARED, { memory_count: total });
        setPage(1);
        handleChanged();
      } else {
        toast.error(response.message || "Failed to clear memories");
      }
    } catch {
      toast.error("Failed to clear memories");
    } finally {
      setIsClearing(false);
    }
  }, [confirm, data?.total_count, handleChanged]);

  const isSearching = query.trim().length > 0;
  const filtered = isSearching ? (searchResults ?? []) : (data?.memories ?? []);
  const totalCount = data?.total_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / MEMORY_PAGE_SIZE));

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Input
          size="sm"
          variant="flat"
          placeholder="Search memories"
          value={query}
          onValueChange={setQuery}
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

      {(isSearching && searchResults === null) || (!isSearching && loading) ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full rounded-2xl" />
          <Skeleton className="h-14 w-full rounded-2xl" />
          <Skeleton className="h-14 w-full rounded-2xl" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center gap-1 text-zinc-500">
          <AiBrain01Icon className="mb-2 size-8 opacity-40" />
          <p className="text-sm">
            {isSearching ? "No memories match your search" : "No memories yet"}
          </p>
          {!isSearching && (
            <p className="text-xs">
              Start a conversation and GAIA will remember the important details
            </p>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl bg-zinc-900/60 py-1">
          {filtered.map((memory) => (
            <MemoryRow
              key={memory.id}
              memory={memory}
              showCategory
              isDeleting={actions.deletingId === memory.id}
              onEdit={actions.setEditingMemory}
              onForget={actions.forgetMemory}
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
            aria-label="Previous page"
            isDisabled={page <= 1}
            onPress={() => setPage(page - 1)}
          >
            <ArrowLeft01Icon className="size-4" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            aria-label="Next page"
            isDisabled={page >= totalPages}
            onPress={() => setPage(page + 1)}
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
