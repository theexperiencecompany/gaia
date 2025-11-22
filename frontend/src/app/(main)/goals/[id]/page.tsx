"use client";

import "@xyflow/react/dist/style.css";

import {
  ConnectionLineType,
  Edge,
  Handle,
  Node,
  Position,
  ReactFlow,
  ReactFlowInstance,
  ReactFlowProvider,
} from "@xyflow/react";
import dagre from "dagre";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { GoalSidebar } from "@/components/layout/sidebar/right-variants/GoalSidebar";
import { MultiStepLoader } from "@/components/ui/shadcn/multi-step-loader";
import { goalsApi } from "@/features/goals/api/goalsApi";
import { Alert01Icon } from '@/icons';
import { truncateTitle } from "@/lib/utils";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { Goal } from "@/types/api/goalsApiTypes";
import { EdgeType, GoalData, NodeData } from "@/types/features/goalTypes";

// Define CustomNode outside of the component to prevent recreation on every render
const CustomNode = React.memo(
  ({
    data,
    onNodeClick,
  }: {
    data: NodeData;
    onNodeClick: (id: string) => void;
  }) => {
    return (
      <>
        <Handle position={Position.Top} type="target" />

        <div
          className={`flex max-w-[250px] min-w-[250px] cursor-pointer flex-row items-center justify-center gap-1 rounded-lg bg-zinc-800 p-4 text-center text-white outline-[3px] outline-zinc-700 transition-all hover:outline-zinc-600`}
          style={
            data.isComplete
              ? {
                  backgroundColor: "rgba(0, 187, 255, 0.2)",
                  color: "rgb(161 161 170)",
                  textDecoration: "line-through",
                  outlineColor: "rgba(0, 187, 255, 0.3)",
                }
              : undefined
          }
          onClick={() => onNodeClick(data.id)}
        >
          {data.label}
        </div>

        <Handle position={Position.Bottom} type="source" />
      </>
    );
  },
);
CustomNode.displayName = "CustomNode";

export default function GoalPage() {
  const [goalData, setGoalData] = useState<GoalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [nodes, setNodes] = useState<Node<NodeData>[]>([]);
  const [edges, setEdges] = useState<Edge<EdgeType>[]>([]);
  const [currentlySelectedNodeId, setCurrentlySelectedNodeId] = useState<
    string | null
  >(null);
  const params = useParams();
  const goalId = typeof params.id === "string" ? params.id : params.id?.[0];

  // Use right sidebar store
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  const handleNodeClick = useCallback((nodeId: string) => {
    setCurrentlySelectedNodeId(nodeId);
  }, []);

  // Memoize nodeTypes to prevent React Flow warning
  const nodeTypes = useMemo(
    () => ({
      customNode: (props: { data: NodeData }) => (
        <CustomNode {...props} onNodeClick={handleNodeClick} />
      ),
    }),
    [handleNodeClick],
  );

  const fetchGoalData = useCallback(async () => {
    try {
      if (!goalId) return;
      setLoading(true);
      const goal = (await goalsApi.fetchGoalById(goalId as string)) as Goal;
      if (goal?.roadmap) {
        setGoalData({
          ...goal,
          created_at: new Date(goal.created_at || Date.now()).toString(),
          description: goal.description || "",
          progress: goal.progress || 0,
          roadmap: goal.roadmap,
        });
        setLoading(false);
        const graph = new dagre.graphlib.Graph();
        graph.setGraph({ rankdir: "TD" });
        graph.setDefaultEdgeLabel(() => ({}));
        goal.roadmap.nodes?.forEach((node) => {
          graph.setNode(node.id, { width: 350, height: 100 });
        });
        goal.roadmap.edges?.forEach((edge) => {
          graph.setEdge(edge.source, edge.target);
        });
        dagre.layout(graph);
        const updatedNodes = goal.roadmap.nodes?.map((node) => {
          const nodePosition = graph.node(node.id);
          return {
            id: node.id,
            position: {
              x: nodePosition?.x || 0,
              y: nodePosition?.y || 0,
            },
            type: "customNode",
            data: {
              id: node.data.id || node.id,
              goalId: node.data.goalId || goal.id,
              title: node.data.title,
              label: node.data.label || node.data.title || "Untitled",
              details: node.data.details || [],
              estimatedTime: node.data.estimatedTime || [],
              resources: node.data.resources || [],
              isComplete: node.data.isComplete || false,
              type: node.data.type,
              subtask_id: node.data.subtask_id,
            },
          };
        });
        setNodes(updatedNodes || []);
        if (updatedNodes && updatedNodes.length > 0) {
          setCurrentlySelectedNodeId(updatedNodes[0]?.id);
        }
        setEdges(goal.roadmap.edges || []);
      } else {
        console.log("initialising roadmap web socket");
        const initiateWebSocket = (goalId: string, goalTitle: string) => {
          const ws = new WebSocket(
            `${process.env.NEXT_PUBLIC_API_BASE_URL}ws/roadmap`,
          );
          ws.onopen = () => {
            ws.send(JSON.stringify({ goal_id: goalId, goal_title: goalTitle }));
            console.log("WebSocket: Generating roadmap...");
          };
          ws.onmessage = (event) => {
            const jsonData = event.data.replace(/^data: /, "");
            const parsedData = JSON.parse(jsonData) || jsonData;
            console.log("Parsed WebSocket response:", parsedData);

            if (parsedData.error)
              return toast.error(
                `Error generating roadmap. Please try again later. Error Message: ${parsedData.error}`,
              );
          };
          ws.onerror = (error) => console.error("WebSocket error:", error);
          ws.onclose = () => {
            console.log("WebSocket closed.");
            fetchGoalData();
            setLoading(false);
          };
        };
        initiateWebSocket(goalId as string, goal.title);
      }
    } catch (error) {
      console.error("Goal fetch error:", error);
      toast.error("Error fetching goal data. Please try again later.");
      setGoalData(null);
    }
  }, [goalId]);

  useEffect(() => {
    if (goalId) fetchGoalData();
  }, [goalId, fetchGoalData]);

  const handleInit = (
    reactFlowInstance: ReactFlowInstance<Node<NodeData>, Edge<EdgeType>>,
  ) => {
    const viewport = reactFlowInstance.getViewport();

    reactFlowInstance.setViewport({
      ...viewport,
      x: viewport.x + 75,
      y: -50,
      zoom: 1,
    });
  };

  // if (goalData === null && !loading) return <div>Page Not Found</div>;
  const handleCheckboxClick = async () => {
    if (!currentlySelectedNodeId) return;

    // Find the currently selected node
    const selectedNode = nodes.find(
      (node) => node.id === currentlySelectedNodeId,
    );

    if (!selectedNode) return;

    const updatedIsComplete = !selectedNode.data.isComplete;

    // Optimistically update the node state locally
    setNodes((prevNodes) =>
      prevNodes.map((node) =>
        node.id === currentlySelectedNodeId
          ? {
              ...node,
              data: {
                ...node.data,
                isComplete: updatedIsComplete,
              },
            }
          : node,
      ),
    );

    // Update the server state
    try {
      await goalsApi.updateNodeStatus(
        selectedNode.data.goalId || goalId || "",
        currentlySelectedNodeId,
        updatedIsComplete,
      );
    } catch (error) {
      console.error("Error updating node status:", error);

      // Revert the change if the update fails
      setNodes((prevNodes) =>
        prevNodes.map((node) =>
          node.id === currentlySelectedNodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  isComplete: !updatedIsComplete,
                },
              }
            : node,
        ),
      );
    }
  };

  // Sync selected node with right sidebar
  useEffect(() => {
    const selectedNode = currentlySelectedNodeId
      ? nodes.find((node) => node.id === currentlySelectedNodeId)
      : null;

    if (selectedNode) {
      setRightSidebarContent(
        <GoalSidebar
          node={selectedNode.data}
          onToggleComplete={handleCheckboxClick}
        />,
      );
      openRightSidebar("sidebar");
    } else {
      closeRightSidebar();
    }
  }, [
    currentlySelectedNodeId,
    nodes,
    setRightSidebarContent,
    openRightSidebar,
    closeRightSidebar,
  ]);

  // Cleanup right sidebar on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  // Create a memoized header component using useCallback for stability
  const rawTitle = goalData?.roadmap?.title || goalData?.title || "New Goal";

  const truncatedTitle = useMemo(() => truncateTitle(rawTitle), [rawTitle]);

  return (
    <>
      <title id="chat_title">{`${truncatedTitle || "New Goal"} | GAIA`}</title>

      <ReactFlowProvider>
        <div className="relative flex h-full w-full flex-row justify-between">
          <div
            className={`relative flex h-screen w-full min-w-full flex-row flex-wrap items-center justify-center gap-4 pb-8 text-background ${
              loading ? "h-screen" : "h-fit"
            }`}
          >
            {loading ? (
              <div className="bg-opacity-50 relative flex h-fit w-fit flex-col items-center justify-center gap-10 overflow-hidden rounded-xl bg-zinc-900 pt-9 pb-0">
                <div className="space-y-2 text-center">
                  <div className="text-xl font-medium text-foreground">
                    Creating your detailed Roadmap.
                  </div>
                  {goalData?.title}
                  <div className="text-medium text-foreground-500">
                    Please Wait. This may take a while.
                  </div>

                  <div className="flex items-center gap-2 text-red-500">
                    <Alert01Icon width={17} />
                    Do not leave this page while the roadmap is being generated.
                  </div>
                </div>
                <div className="px-32">
                  <MultiStepLoader
                    duration={4500}
                    loading={true}
                    loadingStates={[
                      { text: "Setting your goal... Let's get started!" },
                      { text: "Exploring your objectives... Almost there!" },
                      { text: "Adding some details to your vision..." },
                      { text: "Creating milestones to guide you..." },
                      { text: "Building your personalized roadmap..." },
                      { text: "Placing the first pieces of the puzzle..." },
                      {
                        text: "Connecting the dots... Things are coming together!",
                      },
                      { text: "Gathering the resources you’ll need..." },
                      { text: "Estimating time... Getting a clearer picture!" },
                      { text: "Putting the final touches on your plan..." },
                    ]}
                    loop={false}
                  />
                </div>
              </div>
            ) : (
              <>
                <div className="relative h-full w-full">
                  <ReactFlow
                    fitView
                    className="relative"
                    connectionLineType={ConnectionLineType.SmoothStep}
                    edges={edges}
                    elementsSelectable={true}
                    fitViewOptions={{ minZoom: 1.2 }}
                    minZoom={0.2}
                    nodeTypes={nodeTypes}
                    nodes={nodes}
                    nodesConnectable={false}
                    nodesDraggable={false}
                    style={{ background: "transparent" }}
                    onInit={handleInit}
                  >
                    {/* <ZoomSlider className="fixed bottom-[25px] right-[150px]!  left-auto! h-fit top-auto! z-30 dark" /> */}
                  </ReactFlow>
                </div>
              </>
            )}
          </div>
          <div className="bg-custom-gradient2 pointer-events-none absolute bottom-0 left-0 z-1 h-[100px] w-full" />
        </div>
      </ReactFlowProvider>
    </>
  );
}
