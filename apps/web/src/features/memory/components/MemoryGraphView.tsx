"use client";

import { NeuralNetworkIcon } from "@icons";
import { type GraphApiDocument, MemoryGraph } from "@supermemory/memory-graph";
import { useEffect, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { MEMORY_GRAPH_THEME } from "@/features/memory/constants";
import { adaptGraphResponse } from "@/features/memory/utils/graphAdapter";

export function MemoryGraphView() {
  const [documents, setDocuments] = useState<GraphApiDocument[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchGraph = async () => {
      try {
        const response = await memoryApi.getGraph();
        if (!cancelled) setDocuments(adaptGraphResponse(response));
      } catch {
        if (!cancelled) setDocuments([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchGraph();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="h-[65vh] overflow-hidden rounded-2xl bg-[#111111]">
      <MemoryGraph
        documents={documents}
        isLoading={loading}
        variant="consumer"
        colors={MEMORY_GRAPH_THEME}
      >
        <div className="flex h-full flex-col items-center justify-center gap-1 text-zinc-500">
          <NeuralNetworkIcon className="mb-2 size-8 opacity-40" />
          <p className="text-sm">No connections yet</p>
          <p className="text-xs">
            People, places, and projects GAIA learns about will appear here
          </p>
        </div>
      </MemoryGraph>
    </div>
  );
}
