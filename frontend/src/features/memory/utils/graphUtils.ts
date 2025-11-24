import type * as d3 from "d3";

import type { Memory, MemoryRelation } from "@/features/memory/api/memoryApi";

export interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  group: string;
  size: number;
  data?: Memory | { id: string; type: string };
}

export interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  relationship: string;
  value: number;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export function transformMemoryDataToGraph(
  memories: Memory[],
  relations: MemoryRelation[],
): GraphData {
  const nodes: GraphNode[] = [];
  const nodeMap = new Map<string, GraphNode>();

  // Get user ID - assuming it's from the first memory or from relations
  const userId =
    memories[0]?.user_id ||
    relations.find((r) => r.source_type === "user")?.source ||
    "";

  // Add user as central node
  const userNode: GraphNode = {
    id: userId,
    label: "Me",
    type: "user",
    group: "user",
    size: 30,
    data: { id: userId, type: "user" },
  };
  nodes.push(userNode);
  nodeMap.set(userId, userNode);

  // Extract unique entities from relations
  const entities = new Map<string, { id: string; type: string }>();

  relations.forEach((relation) => {
    // Add source entity
    if (!nodeMap.has(relation.source)) {
      entities.set(relation.source, {
        id: relation.source,
        type: relation.source_type,
      });
    }
    // Add target entity
    if (!nodeMap.has(relation.target)) {
      entities.set(relation.target, {
        id: relation.target,
        type: relation.target_type,
      });
    }
  });

  // Add entity nodes
  entities.forEach((entity, entityId) => {
    const node: GraphNode = {
      id: entityId,
      label: entityId
        .replace(/_/g, " ")
        .replace(/\b\w/g, (l) => l.toUpperCase()),
      type: entity.type,
      group: entity.type,
      size: entity.type === "user" ? 30 : entity.type === "person" ? 25 : 20,
      data: entity,
    };
    nodes.push(node);
    nodeMap.set(entityId, node);
  });

  // Create links from relations
  const links: GraphLink[] = relations
    .filter(
      (relation) =>
        nodeMap.has(relation.source) && nodeMap.has(relation.target),
    )
    .map((relation) => ({
      source: relation.source,
      target: relation.target,
      relationship: relation.relationship,
      value: 1,
    }));

  return { nodes, links };
}

export function getNodeTooltipContent(node: GraphNode): string {
  let content = `<strong>${node.label}</strong><br/>Type: ${node.type}`;

  if (node.type === "memory" && node.data) {
    const memory = node.data as Memory;
    content += `<br/>Categories: ${memory.categories?.join(", ") || "None"}`;
    content += `<br/>Created: ${memory.created_at ? new Date(memory.created_at).toLocaleDateString() : "Unknown"}`;
  }

  return content;
}
