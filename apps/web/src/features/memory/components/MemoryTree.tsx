"use client";

import { Skeleton } from "@heroui/skeleton";
import { Spinner } from "@heroui/spinner";
import { Folder01Icon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { ChevronRight } from "@/components/shared/icons";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry, MemoryTreeNode } from "@/features/memory/api/types";
import { EditMemoryModal } from "@/features/memory/components/EditMemoryModal";
import { MemoryRow } from "@/features/memory/components/MemoryRow";
import { useMemoryActions } from "@/features/memory/hooks/useMemoryActions";
import { cn } from "@/lib/utils";

interface MemoryTreeProps {
  onChanged: () => void;
}

export function MemoryTree({ onChanged }: MemoryTreeProps) {
  const [tree, setTree] = useState<MemoryTreeNode[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTree = useCallback(async () => {
    try {
      const response = await memoryApi.getTree();
      setTree(response.tree ?? []);
    } catch {
      setTree([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const handleChanged = useCallback(() => {
    fetchTree();
    onChanged();
  }, [fetchTree, onChanged]);

  const actions = useMemoryActions(handleChanged);

  if (loading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-11 w-full rounded-2xl" />
        <Skeleton className="h-11 w-full rounded-2xl" />
        <Skeleton className="h-11 w-2/3 rounded-2xl" />
      </div>
    );
  }

  if (tree.length === 0) {
    return (
      <div className="flex h-48 flex-col items-center justify-center gap-1 text-zinc-500">
        <Folder01Icon className="mb-2 size-8 opacity-40" />
        <p className="text-sm">No memories filed yet</p>
        <p className="text-xs">
          GAIA organizes what it learns about you into folders as you talk
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-800 py-1">
      {tree.map((node) => (
        <TreeFolder key={node.path} node={node} depth={0} actions={actions} />
      ))}
      <EditMemoryModal
        memory={actions.editingMemory}
        onClose={() => actions.setEditingMemory(null)}
        onSaved={handleChanged}
      />
      <ConfirmationDialog {...actions.confirmationProps} />
    </div>
  );
}

interface TreeFolderProps {
  node: MemoryTreeNode;
  depth: number;
  actions: ReturnType<typeof useMemoryActions>;
}

function TreeFolder({ node, depth, actions }: TreeFolderProps) {
  const [expanded, setExpanded] = useState(false);
  const [memories, setMemories] = useState<MemoryEntry[] | null>(node.memories);
  const [loadingMemories, setLoadingMemories] = useState(false);

  const handleToggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && memories === null) {
      setLoadingMemories(true);
      try {
        const response = await memoryApi.listMemories({
          category: node.path,
          pageSize: 50,
        });
        setMemories(response.memories ?? []);
      } catch {
        setMemories([]);
      } finally {
        setLoadingMemories(false);
      }
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-white/5"
        style={{ paddingLeft: `${16 + depth * 24}px` }}
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-zinc-500 transition-transform",
            expanded && "rotate-90",
          )}
        />
        <Folder01Icon className="size-4 shrink-0 text-zinc-400" />
        <span className="min-w-0 flex-1 truncate text-sm text-zinc-100">
          {node.name}
        </span>
        <span className="shrink-0 text-xs text-zinc-500">{node.count}</span>
      </button>

      {expanded && (
        <div>
          {node.children.map((child) => (
            <TreeFolder
              key={child.path}
              node={child}
              depth={depth + 1}
              actions={actions}
            />
          ))}
          {loadingMemories && (
            <div
              className="py-2"
              style={{ paddingLeft: `${40 + depth * 24}px` }}
            >
              <Spinner size="sm" />
            </div>
          )}
          {memories && memories.length > 0 && (
            <div style={{ paddingLeft: `${24 + depth * 24}px` }}>
              {memories.map((memory) => (
                <MemoryRow
                  key={memory.id}
                  memory={memory}
                  isDeleting={actions.deletingId === memory.id}
                  onEdit={actions.setEditingMemory}
                  onForget={async (target) => {
                    // Pop the row immediately on success — the folder's local
                    // cache otherwise keeps showing the forgotten memory.
                    if (await actions.forgetMemory(target)) {
                      setMemories(
                        (previous) =>
                          previous?.filter((m) => m.id !== target.id) ?? null,
                      );
                    }
                  }}
                />
              ))}
            </div>
          )}
          {memories &&
            memories.length === 0 &&
            node.children.length === 0 &&
            !loadingMemories && (
              <p
                className="py-2 text-xs text-zinc-500"
                style={{ paddingLeft: `${40 + depth * 24}px` }}
              >
                Nothing here yet
              </p>
            )}
        </div>
      )}
    </div>
  );
}
