import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Tab, Tabs } from "@heroui/tabs";
import { List, Network, Plus, Trash2 } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { AiBrain01Icon } from "@/components/shared/icons";
import {
  type Memory,
  memoryApi,
  type MemoryRelation,
} from "@/features/memory/api/memoryApi";
import AddMemoryModal from "@/features/memory/components/AddMemoryModal";
import MemoryGraph from "@/features/memory/components/MemoryGraph";
import { useConfirmation } from "@/hooks/useConfirmation";

export interface MemoryManagementProps {
  className?: string;
  onClose?: () => void;
  autoFetch?: boolean; // Whether to fetch on mount
  onFetch?: (memories: Memory[]) => void; // Callback when memories are fetched
}

export default function MemoryManagement({
  className = "",
  onClose: _onClose,
  autoFetch = true,
  onFetch,
}: MemoryManagementProps) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [relations, setRelations] = useState<MemoryRelation[]>([]);
  const [loading, setLoading] = useState(false);
  const [isAddMemoryModalOpen, setIsAddMemoryModalOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState("list");
  const { confirm, confirmationProps } = useConfirmation();

  const fetchMemories = useCallback(async () => {
    setLoading(true);
    try {
      const response = await memoryApi.fetchMemories();

      setMemories(response.memories || []);
      setRelations(response.relations || []);
      if (onFetch) {
        onFetch(response.memories || []);
      }
    } catch (error) {
      console.error("Error fetching memories:", error);
      toast.error("Failed to load memories");
    } finally {
      setLoading(false);
    }
  }, [onFetch]);

  useEffect(() => {
    if (autoFetch) {
      fetchMemories();
    }
  }, [autoFetch, fetchMemories]);

  const handleDeleteMemory = useCallback(
    async (memoryId: string) => {
      setDeletingId(memoryId);
      try {
        const response = await memoryApi.deleteMemory(memoryId);

        if (response.success) {
          toast.success("Memory deleted");
          fetchMemories();
        } else {
          toast.error(response.message || "Failed to delete memory");
        }
      } catch (error) {
        console.error("Error deleting memory:", error);
        toast.error("Failed to delete memory");
      } finally {
        setDeletingId(null);
      }
    },
    [fetchMemories],
  );

  const handleClearAll = useCallback(async () => {
    const confirmed = await confirm({
      title: "Clear All Memories",
      message:
        "Are you sure you want to clear all memories? This action cannot be undone.",
      confirmText: "Clear All",
      cancelText: "Cancel",
      variant: "destructive",
    });

    if (!confirmed) return;
    try {
      const response = await memoryApi.deleteAllMemories();

      if (response.success) {
        toast.success(response.message || "All memories cleared");
        setMemories([]);
        setRelations([]);
      } else {
        toast.error(response.message || "Failed to clear memories");
      }
    } catch (error) {
      console.error("Error clearing memories:", error);
      toast.error("Failed to clear memories");
    }
  }, [confirm]);

  const MemoryCard = useCallback(
    ({ memory }: { memory: Memory }) => {
      // Format date to be more readable
      const formattedDate = memory.created_at
        ? new Date(memory.created_at).toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          })
        : "";

      return (
        <div>
          <Card className="bg-zinc-800 shadow-none">
            <CardBody className="flex flex-col gap-1">
              <div className="flex flex-row items-center justify-between">
                <div className="flex-1">
                  <p>{memory.content}</p>
                </div>
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  color="danger"
                  onPress={() => handleDeleteMemory(memory.id)}
                  isLoading={deletingId === memory.id}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>

              {/* Additional memory details */}
              <div className="flex w-full items-center justify-between text-xs text-gray-400">
                {formattedDate && <span>{formattedDate}</span>}

                {memory.categories && memory.categories.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {memory.categories.map((category) => (
                      <span
                        key={category}
                        className="rounded-full bg-zinc-700 px-2 py-0.5"
                      >
                        {category.split("_").map((part) => (
                          <span key={part}>
                            {part.charAt(0).toUpperCase() + part.slice(1)}{" "}
                          </span>
                        ))}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </CardBody>
          </Card>
        </div>
      );
    },
    [handleDeleteMemory, deletingId],
  );

  return (
    <div className={`flex h-full min-h-[70vh] flex-col gap-2 ${className}`}>
      <div className="mb-4 flex items-center justify-end">
        <div className="flex gap-2">
          <Button
            size="sm"
            color="primary"
            variant="flat"
            startContent={<Plus className="h-4 w-4" />}
            onPress={() => setIsAddMemoryModalOpen(true)}
          >
            Add Memory
          </Button>
          {memories.length > 0 && (
            <Button
              size="sm"
              color="danger"
              variant="flat"
              onPress={handleClearAll}
            >
              Clear All
            </Button>
          )}
        </div>
      </div>

      {/* Add memory Modal */}
      <AddMemoryModal
        isOpen={isAddMemoryModalOpen}
        onClose={() => setIsAddMemoryModalOpen(false)}
        onMemoryAdded={() => fetchMemories()}
      />

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Image
            alt="GAIA Logo"
            src={"/images/logos/logo.webp"}
            width={30}
            height={30}
            className={`animate-spin`}
          />
        </div>
      ) : memories.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center text-gray-500">
          <AiBrain01Icon className="mb-3 h-12 w-12 opacity-30" />
          <p>No memories yet</p>
          <p className="text-sm">
            Start a conversation and GAIA will remember important details
          </p>
        </div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          <Tabs
            selectedKey={selectedTab}
            onSelectionChange={(key) => setSelectedTab(key as string)}
            variant="underlined"
            classNames={{
              tabList:
                "gap-6 w-full relative rounded-none p-0 border-b border-divider flex justify-center",
              cursor: "w-full bg-primary",
              tab: "max-w-fit px-0",
              tabContent: "group-data-[selected=true]:text-primary",
            }}
          >
            <Tab
              key="list"
              title={
                <div className="flex items-center gap-2">
                  <List className="h-4 w-4" />
                  <span>List View</span>
                </div>
              }
            >
              <div className="mt-4 max-h-[60vh] flex-1 space-y-2 overflow-y-auto pr-2">
                {memories.map((memory) => (
                  <MemoryCard key={memory.id} memory={memory} />
                ))}
              </div>
            </Tab>
            <Tab
              key="graph"
              title={
                <div className="flex items-center gap-2">
                  <Network className="h-4 w-4" />
                  <span>Graph View</span>
                </div>
              }
            >
              <div
                className="mt-4 flex-1"
                style={{ height: "calc(100vh - 300px)" }}
              >
                <MemoryGraph
                  memories={memories}
                  relations={relations}
                  onNodeClick={(node) => {
                    console.log("Node clicked:", node);
                    // Add navigation logic here if needed
                  }}
                />
              </div>
            </Tab>
          </Tabs>
        </div>
      )}

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
}
