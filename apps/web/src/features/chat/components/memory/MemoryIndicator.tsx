"use client";

import { Button } from "@heroui/button";
import { AiBrain01Icon } from "@icons";

interface MemoryResult {
  id: string;
  content: string;
  relevance_score?: number;
  metadata?: Record<string, unknown>;
}

interface MemoryItem {
  id: string;
  content: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

interface MemoryIndicatorProps {
  memoryData?: {
    type?: string;
    operation?: string;
    status?: string;
    results?: MemoryResult[];
    memories?: MemoryItem[];
    count?: number;
    content?: string;
    memory_id?: string;
    error?: string;
    timestamp?: string;
    conversation_id?: string;
  } | null;
  onOpenModal: () => void;
}

type MemoryData = NonNullable<MemoryIndicatorProps["memoryData"]>;

function resolveSuccessText(operation?: string, count?: number): string {
  switch (operation) {
    case "create":
      return "Created a memory";
    case "search":
      if (count === 0) return "No memories found";
      if (count === 1) return "Found 1 memory";
      return `Found ${count} memories`;
    case "list":
      return count === 0 ? "No memories" : `Retrieved ${count} memories`;
    default:
      return "memory operation completed";
  }
}

// Determine what text to display based on memory data, or null when the data
// does not warrant an indicator.
function resolveMemoryText(memoryData: MemoryData): string | null {
  const { type, operation, status, count } = memoryData;

  // Handle new simplified memory_stored type
  if (type === "memory_stored") return "memory stored";
  if (status === "success") return resolveSuccessText(operation, count);
  if (status === "storing") return "Storing memory...";
  if (status === "searching") return "Searching memories...";
  if (status === "retrieving") return "Retrieving memories...";
  return null;
}

export default function MemoryIndicator({
  memoryData,
  onOpenModal,
}: MemoryIndicatorProps) {
  // Derived during render — memoryData is a message's fixed tool payload, so
  // there is nothing to keep in state between renders.
  const displayText = memoryData ? resolveMemoryText(memoryData) : null;
  if (!displayText) return null;

  return (
    <Button
      size="sm"
      variant="flat"
      radius="full"
      className="w-fit text-gray-500"
      startContent={<AiBrain01Icon className="h-4 w-4" />}
      onPress={onOpenModal}
    >
      {displayText}
    </Button>
  );
}
