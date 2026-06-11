"use client";

import { NeuralNetworkIcon } from "@icons";
import { type GraphApiDocument, MemoryGraph } from "@supermemory/memory-graph";
import { useEffect, useRef, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { MemoryEmptyState } from "@/features/memory/components/MemoryEmptyState";
import { MEMORY_GRAPH_THEME } from "@/features/memory/constants";
import { adaptGraphResponse } from "@/features/memory/utils/graphAdapter";

/** Flatten pill border-radii on the graph library's inline-styled controls. */
function useGraphControlFlattener(ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const flatten = () => {
      // Controls panel: absolutely positioned, bottom-left
      const controlsPanel = root.querySelector<HTMLElement>(
        'div[style*="position: absolute"][style*="bottom: 16px"]',
      );
      if (!controlsPanel) return;

      // Fit / Center / zoom wrapper buttons — 9999px pill → 10px
      const pillElements = controlsPanel.querySelectorAll<HTMLElement>(
        'button[style*="border-radius: 9999px"], div[style*="border-radius: 9999px"]',
      );
      for (const el of pillElements) {
        el.style.borderRadius = "10px";
        el.style.border = "none";
        el.style.boxShadow = "none";
      }

      // Zoom − / + inner buttons: keep 4px but strip border
      const zoomBtns = controlsPanel.querySelectorAll<HTMLElement>(
        'button[style*="border-radius: 4px"]',
      );
      for (const el of zoomBtns) {
        el.style.border = "none";
        el.style.backgroundColor = "rgba(255,255,255,0.06)";
      }

      // Legend panel: 12px → 10px, strip border
      const legendPanel = controlsPanel.querySelector<HTMLElement>(
        'div[style*="border-radius: 12px"]',
      );
      if (legendPanel) {
        legendPanel.style.borderRadius = "10px";
        legendPanel.style.border = "none";
        legendPanel.style.boxShadow = "none";
      }
    };

    // Run once after mount and then watch for DOM mutations (graph re-renders)
    flatten();
    const observer = new MutationObserver(flatten);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["style"],
    });

    return () => observer.disconnect();
  }, [ref]);
}

export function MemoryGraphView() {
  const [documents, setDocuments] = useState<GraphApiDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const wrapperRef = useRef<HTMLDivElement>(null);

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

  useGraphControlFlattener(wrapperRef);

  return (
    <div
      ref={wrapperRef}
      className="h-[65vh] overflow-hidden rounded-2xl bg-[#111111]"
    >
      <MemoryGraph
        documents={documents}
        isLoading={loading}
        variant="consumer"
        colors={MEMORY_GRAPH_THEME}
      >
        <MemoryEmptyState
          icon={NeuralNetworkIcon}
          title="No connections yet"
          description="People, places, and projects GAIA learns about will appear here"
        />
      </MemoryGraph>
    </div>
  );
}
