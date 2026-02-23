"use client";

import "@xyflow/react/dist/style.css";

import { Chip } from "@heroui/chip";
import { Book01Icon, Cancel01Icon, Timer02Icon } from "@icons";
import {
  ConnectionLineType,
  Handle,
  type Node,
  Position,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import dagre from "dagre";
import React, { useCallback, useEffect, useMemo, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DemoNodeData extends Record<string, unknown> {
  id: string;
  label: string;
  details: string[];
  estimatedTime: string;
  resources: string[];
  type: string;
  isComplete: boolean;
}

// ─── Static demo data ─────────────────────────────────────────────────────────

const GOAL_NODES_RAW: Array<{ id: string; data: DemoNodeData }> = [
  {
    id: "1",
    data: {
      id: "1",
      label: "Define MVP Scope",
      details: [
        "Write product spec",
        "Prioritise features by impact",
        "Agree on scope with team",
      ],
      estimatedTime: "3 days",
      resources: [
        "Product spec template",
        "Jobs-to-be-done framework",
        "MoSCoW prioritisation",
      ],
      type: "milestone",
      isComplete: true,
    },
  },
  {
    id: "2",
    data: {
      id: "2",
      label: "UI/UX Design",
      details: [
        "Build component library",
        "Define colour tokens",
        "Create key page wireframes",
      ],
      estimatedTime: "1 week",
      resources: [
        "Figma tokens guide",
        "Tailwind CSS docs",
        "Radix UI primitives",
      ],
      type: "task",
      isComplete: true,
    },
  },
  {
    id: "3",
    data: {
      id: "3",
      label: "Backend API",
      details: [
        "Set up FastAPI project",
        "Define REST endpoints",
        "Write OpenAPI schema",
      ],
      estimatedTime: "2 weeks",
      resources: [
        "FastAPI docs",
        "PostgreSQL best practices",
        "Pydantic v2 guide",
      ],
      type: "task",
      isComplete: true,
    },
  },
  {
    id: "4",
    data: {
      id: "4",
      label: "Agent Integration",
      details: [
        "Wire tool calling",
        "Set up memory store",
        "Test multi-step reasoning",
      ],
      estimatedTime: "1 week",
      resources: [
        "LangGraph docs",
        "Anthropic tool use guide",
        "Agent evaluation patterns",
      ],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "5",
    data: {
      id: "5",
      label: "DevOps & Infrastructure",
      details: [
        "Configure Docker Compose",
        "Set up cloud provider",
        "Configure environment secrets",
      ],
      estimatedTime: "4 days",
      resources: ["Docker docs", "Railway.app guide", "12-factor app"],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "6",
    data: {
      id: "6",
      label: "CI/CD Pipeline",
      details: [
        "Set up GitHub Actions",
        "Write test suite",
        "Automate staging deploys",
      ],
      estimatedTime: "3 days",
      resources: [
        "GitHub Actions docs",
        "pytest best practices",
        "Nx monorepo CI guide",
      ],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "7",
    data: {
      id: "7",
      label: "Integration Testing",
      details: [
        "End-to-end user flows",
        "Performance benchmarks",
        "Fix critical bugs",
      ],
      estimatedTime: "1 week",
      resources: [
        "Playwright docs",
        "k6 load testing",
        "Sentry error tracking",
      ],
      type: "milestone",
      isComplete: false,
    },
  },
  {
    id: "8",
    data: {
      id: "8",
      label: "Beta Launch",
      details: [
        "Onboard 20 beta users",
        "Collect structured feedback",
        "Triage & fix blockers",
      ],
      estimatedTime: "2 weeks",
      resources: [
        "Beta feedback template",
        "Linear bug tracking",
        "Hotjar session replay",
      ],
      type: "milestone",
      isComplete: false,
    },
  },
];

const GOAL_EDGES = [
  { id: "e1-2", source: "1", target: "2" },
  { id: "e1-3", source: "1", target: "3" },
  { id: "e1-5", source: "1", target: "5" },
  { id: "e2-4", source: "2", target: "4" },
  { id: "e3-4", source: "3", target: "4" },
  { id: "e5-6", source: "5", target: "6" },
  { id: "e4-7", source: "4", target: "7" },
  { id: "e6-7", source: "6", target: "7" },
  { id: "e7-8", source: "7", target: "8" },
];

// ─── Layout ───────────────────────────────────────────────────────────────────

function buildLayoutedNodes(): Node<DemoNodeData>[] {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "TD", nodesep: 30, ranksep: 50 });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const n of GOAL_NODES_RAW)
    graph.setNode(n.id, { width: 220, height: 56 });
  for (const e of GOAL_EDGES) graph.setEdge(e.source, e.target);
  dagre.layout(graph);

  return GOAL_NODES_RAW.map((n) => {
    const pos = graph.node(n.id);
    return {
      id: n.id,
      position: { x: pos.x - 110, y: pos.y - 28 },
      type: "demoGoalNode",
      data: n.data,
    };
  });
}

// ─── Custom node ──────────────────────────────────────────────────────────────

const DemoGoalNode = React.memo(
  ({
    data,
    onSelect,
    isSelected,
  }: {
    data: DemoNodeData;
    onSelect: (id: string) => void;
    isSelected: boolean;
  }) => (
    <>
      <Handle position={Position.Top} type="target" />
      <div
        onClick={() => onSelect(data.id)}
        className="flex min-w-[220px] max-w-[220px] cursor-pointer items-center justify-center rounded-xl px-3 py-3.5 text-center text-sm font-medium outline outline-[2px] transition-all"
        style={
          data.isComplete
            ? {
                backgroundColor: "rgba(0,187,255,0.12)",
                outlineColor: isSelected ? "#00bbff" : "rgba(0,187,255,0.25)",
                textDecoration: "line-through",
                color: "rgb(113 113 122)",
              }
            : {
                backgroundColor: isSelected
                  ? "rgba(0,187,255,0.08)"
                  : "#27272a",
                outlineColor: isSelected ? "#00bbff" : "#3f3f46",
                color: isSelected ? "#fff" : "rgb(212 212 216)",
              }
        }
      >
        {data.label}
      </div>
      <Handle position={Position.Bottom} type="source" />
    </>
  ),
);
DemoGoalNode.displayName = "DemoGoalNode";

// ─── Right sidebar ────────────────────────────────────────────────────────────

function DemoGoalNodeSidebar({
  node,
  onClose,
}: {
  node: DemoNodeData;
  onClose: () => void;
}) {
  return (
    <div
      className="flex h-full w-[280px] shrink-0 flex-col border-l border-zinc-800"
      style={{ backgroundColor: "#141414" }}
    >
      {/* Close button */}
      <div className="flex shrink-0 items-center justify-end px-4 pt-3">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
        >
          <Cancel01Icon className="size-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-4">
        <div className="space-y-4">
          {/* Title */}
          <h2
            className={`text-xl font-medium leading-tight ${
              node.isComplete ? "text-zinc-500 line-through" : "text-zinc-100"
            }`}
          >
            {node.label}
          </h2>

          {/* Type badge */}
          <Chip
            size="sm"
            variant="flat"
            color={node.isComplete ? "success" : "default"}
            radius="sm"
            className="capitalize"
          >
            {node.isComplete ? "Completed" : node.type}
          </Chip>

          {/* Details */}
          {node.details.length > 0 && (
            <p
              className={`text-sm leading-relaxed ${
                node.isComplete ? "text-zinc-600" : "text-zinc-400"
              }`}
            >
              {node.details.join(" · ")}
            </p>
          )}

          {/* Estimated time */}
          {node.estimatedTime && (
            <div className="flex items-center gap-2 rounded-xl bg-primary/10 px-3 py-2">
              <Timer02Icon
                width={16}
                height={16}
                className="shrink-0 text-primary"
              />
              <span className="text-sm text-zinc-300">
                <span className="mr-1 text-xs text-zinc-500">
                  Estimated time:
                </span>
                {node.estimatedTime}
              </span>
            </div>
          )}

          {/* Resources */}
          {node.resources.length > 0 && (
            <div className="rounded-xl bg-zinc-800/40 p-4">
              <div className="mb-2.5 flex items-center gap-2 text-sm font-medium text-zinc-300">
                <Book01Icon width={16} height={16} />
                Resources
              </div>
              <ul className="space-y-1.5">
                {node.resources.map((r) => (
                  <li key={r}>
                    <a
                      href={`https://www.google.com/search?q=${encodeURIComponent(r)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-zinc-400 underline decoration-zinc-600 underline-offset-4 transition-colors hover:text-primary hover:decoration-primary"
                    >
                      {r}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-zinc-800/60 px-5 py-3 text-center text-xs capitalize text-zinc-600">
        {node.type} · Launch GAIA v1.0
      </div>
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

const STATIC_NODES = buildLayoutedNodes();

export default function DemoGoalsView() {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("4");

  const selectedNodeData = useMemo(
    () =>
      selectedNodeId
        ? (GOAL_NODES_RAW.find((n) => n.id === selectedNodeId)?.data ?? null)
        : null,
    [selectedNodeId],
  );

  const handleNodeSelect = useCallback((id: string) => {
    setSelectedNodeId((prev) => (prev === id ? null : id));
  }, []);

  const nodeTypes = useMemo(
    () => ({
      demoGoalNode: (props: { data: DemoNodeData }) => (
        <DemoGoalNode
          {...props}
          isSelected={props.data.id === selectedNodeId}
          onSelect={handleNodeSelect}
        />
      ),
    }),
    [selectedNodeId, handleNodeSelect],
  );

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Graph */}
      <div className="relative flex-1">
        <div className="absolute inset-0 z-10 flex items-start justify-center pt-3">
          <span className="rounded-full bg-zinc-900/80 px-3 py-1 text-[11px] font-medium tracking-wide text-zinc-500 backdrop-blur-sm">
            Launch GAIA v1.0
          </span>
        </div>
        <ReactFlowProvider>
          <ReactFlow
            nodes={STATIC_NODES}
            edges={GOAL_EDGES}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.3, minZoom: 0.5 }}
            connectionLineType={ConnectionLineType.SmoothStep}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            panOnDrag={true}
            zoomOnScroll={false}
            style={{ background: "transparent" }}
            proOptions={{ hideAttribution: true }}
          />
        </ReactFlowProvider>
      </div>

      {/* Node detail sidebar */}
      {selectedNodeData && (
        <DemoGoalNodeSidebar
          node={selectedNodeData}
          onClose={() => setSelectedNodeId(null)}
        />
      )}
    </div>
  );
}
