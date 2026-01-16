"use client";

import { Button } from "@heroui/button";
import { useEffect, useState } from "react";

import { AiBrain01Icon } from "@/icons";

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

export default function MemoryIndicator({
  memoryData,
  onOpenModal,
}: MemoryIndicatorProps) {
  const [displayText, setDisplayText] = useState<string>("");
  const [showIndicator, setShowIndicator] = useState(false);

  useEffect(() => {
    // Determine what text to display based on memory data
    if (memoryData) {
      const { type, operation, status, count } = memoryData;

      // Handle new simplified memory_stored type
      if (type === "memory_stored") {
        setDisplayText("memory stored");
        setShowIndicator(true);
      } else if (status === "success") {
        switch (operation) {
          case "create":
            setDisplayText("Created a memory");
            break;
          case "search":
            if (count === 0) {
              setDisplayText("No memories found");
            } else if (count === 1) {
              setDisplayText("Found 1 memory");
            } else {
              setDisplayText(`Found ${count} memories`);
            }
            break;
          case "list":
            if (count === 0) {
              setDisplayText("No memories");
            } else {
              setDisplayText(`Retrieved ${count} memories`);
            }
            break;
          default:
            setDisplayText("memory operation completed");
        }
        setShowIndicator(true);
      } else if (status === "storing") {
        setDisplayText("Storing memory...");
        setShowIndicator(true);
      } else if (status === "searching") {
        setDisplayText("Searching memories...");
        setShowIndicator(true);
      } else if (status === "retrieving") {
        setDisplayText("Retrieving memories...");
        setShowIndicator(true);
      }
    }
  }, [memoryData]);

  if (!showIndicator && !displayText) return null;

  return (
    <>
      {showIndicator && (
        <Button
          size="sm"
          variant="flat"
          radius="full"
          className="w-fit text-foreground-500"
          startContent={<AiBrain01Icon className="h-4 w-4" />}
          onPress={onOpenModal}
        >
          {displayText}
        </Button>
      )}
    </>
  );
}
