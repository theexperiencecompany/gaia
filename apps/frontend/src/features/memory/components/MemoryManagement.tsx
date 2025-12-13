import { Button, ButtonGroup } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Tab, Tabs } from "@heroui/tabs";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  type Memory,
  type MemoryRelation,
  memoryApi,
} from "@/features/memory/api/memoryApi";
import AddMemoryModal from "@/features/memory/components/AddMemoryModal";
import MemoryGraph from "@/features/memory/components/MemoryGraph";
import { useConfirmation } from "@/hooks/useConfirmation";
import {
  AiBrain01Icon,
  ArrowDown01Icon,
  Delete02Icon,
  FileEmpty02Icon,
  Image02Icon,
  ListViewIcon,
  NeuralNetworkIcon,
  PlusSignIcon,
} from "@/icons";

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
  const [isClearing, setIsClearing] = useState(false);
  const [selectedTab, setSelectedTab] = useState("graph");
  const [selectedExportType, setSelectedExportType] = useState<Set<string>>(
    new Set(["png"]),
  );
  const graphExportRef = useRef<{
    exportAsSVG: () => void;
    exportAsPNG: () => void;
  }>(null);
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

    setIsClearing(true);
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
    } finally {
      setIsClearing(false);
    }
  }, [confirm]);

  const handleExport = useCallback(() => {
    const exportType = Array.from(selectedExportType)[0];
    if (exportType === "svg") {
      graphExportRef.current?.exportAsSVG();
      toast.success("Exporting as SVG...");
    } else {
      graphExportRef.current?.exportAsPNG();
      toast.success("Exporting as PNG...");
    }
  }, [selectedExportType]);

  const selectedExportValue = Array.from(selectedExportType)[0];
  const exportLabelsMap: Record<string, string> = {
    png: "PNG",
    svg: "SVG",
  };
  const exportDescriptionsMap: Record<string, string> = {
    png: "Export graph as high-quality PNG image",
    svg: "Export graph as scalable SVG vector",
  };

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
                  <Delete02Icon className="h-4 w-4" />
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
      <AddMemoryModal
        isOpen={isAddMemoryModalOpen}
        onClose={() => setIsAddMemoryModalOpen(false)}
        onMemoryAdded={() => fetchMemories()}
      />

      {memories.length === 0 && !loading ? (
        <div className="flex h-40 flex-col items-center justify-center text-gray-500">
          <AiBrain01Icon className="mb-3 h-12 w-12 opacity-30" />
          <p>No memories yet</p>
          <p className="text-sm">
            Start a conversation and GAIA will remember important details
          </p>
          <Button
            size="sm"
            color="primary"
            variant="flat"
            className="mt-4"
            startContent={<PlusSignIcon className="h-4 w-4" />}
            onPress={() => setIsAddMemoryModalOpen(true)}
          >
            Add Memory
          </Button>
        </div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex items-center justify-between">
            <Tabs
              selectedKey={selectedTab}
              onSelectionChange={(key) => setSelectedTab(key as string)}
              variant="light"
            >
              <Tab
                key="graph"
                title={
                  <div className="flex items-center gap-2">
                    <NeuralNetworkIcon className="h-4 w-4" />
                    <span>Graph View</span>
                  </div>
                }
              />
              <Tab
                key="list"
                title={
                  <div className="flex items-center gap-2">
                    <ListViewIcon className="h-4 w-4" />
                    <span>List View</span>
                  </div>
                }
              />
            </Tabs>

            <div className="flex gap-2">
              {memories.length > 0 && (
                <Button
                  color="danger"
                  variant="flat"
                  onPress={handleClearAll}
                  isLoading={isClearing}
                >
                  Clear All
                </Button>
              )}

              {selectedTab === "graph" && (
                <ButtonGroup variant="flat">
                  <Button
                    onPress={handleExport}
                    startContent={
                      selectedExportValue === "png" ? (
                        <Image02Icon
                          className="h-5 min-h-5 w-5 min-w-5"
                          color="currentColor"
                        />
                      ) : (
                        <FileEmpty02Icon
                          className="h-5 min-h-5 w-5 min-w-5"
                          color="currentColor"
                        />
                      )
                    }
                  >
                    Export as {exportLabelsMap[selectedExportValue]}
                  </Button>
                  <Dropdown placement="bottom-end">
                    <DropdownTrigger>
                      <Button isIconOnly>
                        <ArrowDown01Icon className="h-4 w-4" />
                      </Button>
                    </DropdownTrigger>
                    <DropdownMenu
                      disallowEmptySelection
                      aria-label="Export options"
                      className="max-w-[300px]"
                      selectedKeys={selectedExportType}
                      selectionMode="single"
                      onSelectionChange={(keys) =>
                        setSelectedExportType(keys as Set<string>)
                      }
                    >
                      <DropdownItem
                        key="png"
                        description={exportDescriptionsMap.png}
                        startContent={
                          <Image02Icon
                            className="h-6 min-h-6 w-6 min-w-6"
                            color="currentColor"
                          />
                        }
                      >
                        {exportLabelsMap.png}
                      </DropdownItem>
                      <DropdownItem
                        key="svg"
                        description={exportDescriptionsMap.svg}
                        startContent={
                          <FileEmpty02Icon
                            className="h-6 min-h-6 w-6 min-w-6"
                            color="currentColor"
                          />
                        }
                      >
                        {exportLabelsMap.svg}
                      </DropdownItem>
                    </DropdownMenu>
                  </Dropdown>
                </ButtonGroup>
              )}
              <Button
                color="primary"
                startContent={<PlusSignIcon className="h-4 w-4" />}
                onPress={() => setIsAddMemoryModalOpen(true)}
              >
                Add Memory
              </Button>
            </div>
          </div>

          {/* Tab content */}
          <div className="mt-4 flex-1">
            {selectedTab === "list" &&
              (loading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: Simply mapping skeletons
                    <Card key={i} className="bg-zinc-800 shadow-none">
                      <CardBody>
                        <div className="flex animate-pulse flex-col gap-2">
                          <div className="h-4 w-3/4 rounded bg-zinc-700" />
                          <div className="h-3 w-1/2 rounded bg-zinc-700" />
                        </div>
                      </CardBody>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="max-h-[80vh] space-y-2 overflow-y-auto pr-2">
                  {memories.map((memory) => (
                    <MemoryCard key={memory.id} memory={memory} />
                  ))}
                </div>
              ))}

            {selectedTab === "graph" && (
              <>
                {loading ? (
                  <div className="flex h-full items-center justify-center">
                    <Image
                      alt="GAIA Logo"
                      src={"/images/logos/logo.webp"}
                      width={30}
                      height={30}
                      className="animate-spin"
                    />
                  </div>
                ) : (
                  <div className="h-[80vh]">
                    <MemoryGraph
                      ref={graphExportRef}
                      memories={memories}
                      relations={relations}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
}
