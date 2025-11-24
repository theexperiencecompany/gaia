import { Card, CardBody } from "@heroui/card";
import * as d3 from "d3";
import React, { useEffect, useRef, useState } from "react";

import {
  type DummyLink,
  type DummyNode,
  memoryLinks,
  memoryNodes,
} from "../../constants/data";

export default function MemoryGraphDemo() {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNode, setSelectedNode] = useState<DummyNode | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    content: string;
    visible: boolean;
  }>({
    x: 0,
    y: 0,
    content: "",
    visible: false,
  });

  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;

    const container = containerRef.current;
    const svg = d3.select(svgRef.current);

    // Clear previous content
    svg.selectAll("*").remove();

    const width = container.clientWidth;
    const height = container.clientHeight;

    // Use imported dummy data for memory graph
    const nodes: DummyNode[] = memoryNodes;

    const links: DummyLink[] = memoryLinks;

    // Enhanced color mapping for different node groups
    const colorMapping: Record<string, string> = {
      user: "#00bbff",
      work: "#ef4444",
      family: "#f59e0b",
      personal: "#ec4899",
      health: "#10b981",
      learning: "#8b5cf6",
      social: "#06b6d4",
      professional: "#84cc16",
      future: "#f97316",
    };

    const colorScale = (group: string) => colorMapping[group] || "#6b7280";

    // Center user node initially
    const userNode = nodes.find((n) => n.type === "user");
    if (userNode) {
      userNode.x = width / 2;
      userNode.y = height / 2;
    }

    // Create simulation with enhanced forces
    const simulation = d3
      .forceSimulation<DummyNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<DummyNode, DummyLink>(links)
          .id((d) => d.id)
          .distance((d) => {
            const source = d.source as DummyNode;
            const target = d.target as DummyNode;
            if (source.type === "user" || target.type === "user") return 60;
            return 40;
          })
          .strength(0.8),
      )
      .force("charge", d3.forceManyBody().strength(-800))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3.forceCollide<DummyNode>().radius((d) => d.size + 10),
      );

    // Create container group
    const g = svg.append("g");

    // Create zoom behavior
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);

    // Center view on user node after simulation settles
    const centerOnUser = () => {
      if (userNode && userNode.x && userNode.y) {
        const scale = 1.2;
        const translateX = width / 2 - userNode.x * scale;
        const translateY = height / 2 - userNode.y * scale;

        svg
          .transition()
          .duration(1000)
          .call(
            zoom.transform,
            d3.zoomIdentity.translate(translateX, translateY).scale(scale),
          );
      }
    };

    // Center after simulation runs for a bit
    setTimeout(centerOnUser, 1500);

    // Create links
    const link = g
      .selectAll<SVGLineElement, DummyLink>(".link")
      .data(links)
      .join("line")
      .attr("class", "link")
      .attr("stroke", "#6b7280")
      .attr("stroke-opacity", 0.4)
      .attr("stroke-width", 1.5);

    // Create node groups
    const nodeGroup = g
      .selectAll<SVGGElement, DummyNode>(".node-group")
      .data(nodes)
      .join("g")
      .attr("class", "node-group")
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, DummyNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      );

    // Add circles for non-user nodes
    nodeGroup
      .filter((d) => d.type !== "user")
      .append("circle")
      .attr("r", (d: DummyNode) => d.size)
      .attr("fill", (d: DummyNode) => colorScale(d.group))
      .attr("stroke", "#1f2937")
      .attr("stroke-width", 1.5);

    // Add special styling for user node
    nodeGroup
      .filter((d) => d.type === "user")
      .append("circle")
      .attr("r", (d: DummyNode) => d.size)
      .attr("fill", colorScale("user"))
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 2);

    // Create node labels
    nodeGroup
      .append("text")
      .attr("class", "node-label")
      .attr("text-anchor", "middle")
      .attr("dy", ".35em")
      .attr("font-size", "9px")
      .attr("font-weight", "500")
      .attr("fill", "#f9fafb")
      .attr("pointer-events", "none")
      .text((d: DummyNode) =>
        d.label.length > 30 ? `${d.label.substring(0, 20)}...` : d.label,
      );

    // Add event handlers for interactivity
    nodeGroup
      .on("click", (_event, d) => {
        setSelectedNode(d);
        // Highlight selected node
        nodeGroup.selectAll("circle").each(function (n) {
          const node = n as DummyNode;
          const strokeWidth =
            node.id === d.id ? 3 : node.type === "user" ? 2 : 1.5;
          d3.select(this).attr("stroke-width", strokeWidth);
        });
      })
      .on("mouseover", (event, d) => {
        const [x, y] = d3.pointer(event, container);
        const content = `<strong>${d.label}</strong><br/>Type: ${d.type}<br/>${d.description || ""}`;

        setTooltip({
          x: x + 10,
          y: y - 10,
          content,
          visible: true,
        });

        // Highlight node on hover
        d3.select(event.currentTarget)
          .select("circle")
          .attr("stroke", "#ffffff")
          .attr("stroke-width", 3);
      })
      .on("mouseout", (event, d) => {
        setTooltip((prev) => ({ ...prev, visible: false }));

        // Reset node styling
        d3.select(event.currentTarget)
          .select("circle")
          .attr("stroke", d.type === "user" ? "#ffffff" : "#1f2937")
          .attr(
            "stroke-width",
            selectedNode?.id === d.id ? 3 : d.type === "user" ? 2 : 1.5,
          );
      });

    // Update positions on simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d: DummyLink) => (d.source as DummyNode).x!)
        .attr("y1", (d: DummyLink) => (d.source as DummyNode).y!)
        .attr("x2", (d: DummyLink) => (d.target as DummyNode).x!)
        .attr("y2", (d: DummyLink) => (d.target as DummyNode).y!);

      nodeGroup.attr("transform", (d: DummyNode) => `translate(${d.x},${d.y})`);
    });

    // Run simulation for a limited number of ticks for a nice animation
    simulation.alpha(1).restart();

    // Cleanup function
    return () => {
      simulation.stop();
    };
  }, [selectedNode]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        className="h-full w-full cursor-grab active:cursor-grabbing"
      >
        <svg ref={svgRef} width="100%" height="100%" />
      </div>

      {/* Tooltip */}
      {tooltip.visible && (
        <div
          className="pointer-events-none absolute z-10"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <Card className="border border-zinc-600 bg-zinc-800 shadow-lg">
            <CardBody className="p-2">
              <div
                className="max-w-48 text-xs text-zinc-100"
                dangerouslySetInnerHTML={{ __html: tooltip.content }}
              />
            </CardBody>
          </Card>
        </div>
      )}

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="absolute bottom-2 left-2 z-10">
          <Card className="border border-zinc-600 bg-zinc-800/90 backdrop-blur-sm">
            <CardBody className="p-2">
              <div className="text-xs text-zinc-100">
                <div className="font-semibold">{selectedNode.label}</div>
                <div className="text-zinc-300">{selectedNode.description}</div>
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}
