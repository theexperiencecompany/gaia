import { Card, CardBody } from "@heroui/card";
import * as d3 from "d3";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import type { Memory, MemoryRelation } from "@/features/memory/api/memoryApi";
import {
  type GraphLink,
  type GraphNode,
  getNodeTooltipContent,
  transformMemoryDataToGraph,
} from "@/features/memory/utils/graphUtils";

interface MemoryGraphProps {
  memories: Memory[];
  relations: MemoryRelation[];
  onNodeClick?: (node: GraphNode) => void;
  className?: string;
}

export interface MemoryGraphHandle {
  exportAsSVG: () => void;
  exportAsPNG: () => void;
}

const MemoryGraph = forwardRef<MemoryGraphHandle, MemoryGraphProps>(
  ({ memories, relations, onNodeClick, className = "" }, ref) => {
    const svgRef = useRef<SVGSVGElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [_selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
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
    const [legendItems, setLegendItems] = useState<
      Array<{ type: string; color: string }>
    >([]);
    const user = useUser();

    const exportAsSVG = useCallback(() => {
      if (!svgRef.current) return;

      const svgElement = svgRef.current;

      // Clone the SVG to avoid modifying the original
      const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement;

      // Get the graph group and its bounding box
      const graphGroup = clonedSvg.querySelector("g");
      if (graphGroup) {
        const bbox = (svgElement.querySelector("g") as SVGGElement).getBBox();

        // Add padding around the graph
        const padding = 50;
        const viewBoxWidth = bbox.width + padding * 2;
        const viewBoxHeight = bbox.height + padding * 2;
        const viewBoxX = bbox.x - padding;
        const viewBoxY = bbox.y - padding;

        // Set viewBox to center the graph
        clonedSvg.setAttribute(
          "viewBox",
          `${viewBoxX} ${viewBoxY} ${viewBoxWidth} ${viewBoxHeight}`,
        );
        clonedSvg.setAttribute("width", viewBoxWidth.toString());
        clonedSvg.setAttribute("height", viewBoxHeight.toString());

        // Remove any transform on the graph group to center it properly
        graphGroup.removeAttribute("transform");
      }

      const svgData = new XMLSerializer().serializeToString(clonedSvg);
      const svgBlob = new Blob([svgData], {
        type: "image/svg+xml;charset=utf-8",
      });
      const svgUrl = URL.createObjectURL(svgBlob);
      const downloadLink = document.createElement("a");

      downloadLink.href = svgUrl;
      downloadLink.download = "memory-graph.svg";
      document.body.appendChild(downloadLink);
      downloadLink.click();
      document.body.removeChild(downloadLink);
      URL.revokeObjectURL(svgUrl);
    }, []);

    const exportAsPNG = useCallback(() => {
      if (!svgRef.current) return;

      const svgElement = svgRef.current;

      // Clone the SVG to avoid modifying the original
      const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement;

      // Get the graph group and its bounding box
      const graphGroup = clonedSvg.querySelector("g");
      let bbox = { x: 0, y: 0, width: 800, height: 600 }; // default values

      if (graphGroup) {
        bbox = (svgElement.querySelector("g") as SVGGElement).getBBox();
      }

      // Add padding around the graph
      const padding = 100;
      const exportWidth = bbox.width + padding * 2;
      const exportHeight = bbox.height + padding * 2;
      const viewBoxX = bbox.x - padding;
      const viewBoxY = bbox.y - padding;

      // Set viewBox to center the graph
      clonedSvg.setAttribute(
        "viewBox",
        `${viewBoxX} ${viewBoxY} ${exportWidth} ${exportHeight}`,
      );
      clonedSvg.setAttribute("width", exportWidth.toString());
      clonedSvg.setAttribute("height", exportHeight.toString());

      // Remove any transform on the graph group
      if (graphGroup) {
        graphGroup.removeAttribute("transform");
      }

      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      const img = new Image();

      // High resolution settings - 4x for crisp quality
      const scale = 4;
      canvas.width = exportWidth * scale;
      canvas.height = exportHeight * scale;

      // Scale the context for high DPI
      ctx?.scale(scale, scale);

      // Set background for better contrast
      if (ctx) {
        ctx.fillStyle = "#18181b"; // zinc-900 background
        ctx.fillRect(0, 0, exportWidth, exportHeight);
      }

      img.onload = () => {
        ctx?.drawImage(img, 0, 0, exportWidth, exportHeight);

        canvas.toBlob(
          (blob) => {
            if (blob) {
              const url = URL.createObjectURL(blob);
              const downloadLink = document.createElement("a");
              downloadLink.href = url;
              downloadLink.download = "memory-graph.png";
              document.body.appendChild(downloadLink);
              downloadLink.click();
              document.body.removeChild(downloadLink);
              URL.revokeObjectURL(url);
            }
          },
          "image/png",
          1.0,
        ); // Maximum quality
      };

      const svgData = new XMLSerializer().serializeToString(clonedSvg);
      const svgBlob = new Blob([svgData], {
        type: "image/svg+xml;charset=utf-8",
      });
      const url = URL.createObjectURL(svgBlob);
      img.src = url;
    }, []);

    useImperativeHandle(ref, () => ({
      exportAsSVG,
      exportAsPNG,
    }));

    useEffect(() => {
      if (!svgRef.current || !containerRef.current) return;

      const container = containerRef.current;
      const svg = d3.select(svgRef.current);

      // Clear previous content
      svg.selectAll("*").remove();

      const width = container.clientWidth;
      const height = container.clientHeight;

      // Use utility function to transform data
      const { nodes, links } = transformMemoryDataToGraph(memories, relations);

      // Get unique node types and sort them alphabetically
      const nodeTypes = Array.from(new Set(nodes.map((n) => n.group))).sort();

      // Deterministic hash function for string to number
      const stringToHash = (str: string): number => {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
          const char = str.charCodeAt(i);
          hash = (hash << 5) - hash + char;
          hash = hash & hash; // Convert to 32-bit integer
        }
        return Math.abs(hash);
      };

      // Generate color from hash with good saturation and lightness
      const hashToColor = (str: string): string => {
        const hash = stringToHash(str);
        const hue = hash % 360;
        const saturation = 65 + (hash % 20); // 65-85%
        const lightness = 50 + (hash % 15); // 50-65%
        return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
      };

      // Assign colors to node types deterministically
      const colorMapping: Record<string, string> = {};
      nodeTypes.forEach((type) => {
        colorMapping[type] = hashToColor(type);
      });

      // Create color scale
      const colorScale = (group: string) => colorMapping[group] || "#6b7280";

      // Set legend items
      setLegendItems(
        nodeTypes.map((type) => ({
          type: type
            .replace(/_/g, " ")
            .replace(/\b\w/g, (l) => l.toUpperCase()),
          color: colorMapping[type],
        })),
      );

      // Find the user node to center it initially
      const userNode = nodes.find((n) => n.type === "user");
      if (userNode) {
        userNode.x = width / 2;
        userNode.y = height / 2;
      }

      // Create simulation
      const simulation = d3
        .forceSimulation<GraphNode>(nodes)
        .force(
          "link",
          d3
            .forceLink<GraphNode, GraphLink>(links)
            .id((d) => d.id)
            .distance((d) => {
              // Increased distances for better spacing
              const source = d.source as GraphNode;
              const target = d.target as GraphNode;
              if (source.type === "user" || target.type === "user") return 400;

              return 500;
            })
            .strength((d) => {
              // Stronger links for user connections
              const source = d.source as GraphNode;
              const target = d.target as GraphNode;
              if (source.type === "user" || target.type === "user") {
                return 1.2;
              }
              return 0.8;
            }),
        )
        .force("charge", d3.forceManyBody().strength(-3000))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force(
          "collision",
          d3.forceCollide().radius((d) => (d as GraphNode).size + 50),
        );

      // Create zoom behavior
      const zoom = d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
          g.attr("transform", event.transform);
        });

      svg.call(zoom);

      // Create container group
      const g = svg.append("g");

      // Create links
      const link = g
        .selectAll<SVGLineElement, GraphLink>(".link")
        .data(links)
        .join("line")
        .attr("class", "link")
        .attr("stroke", "#6b7280")
        .attr("stroke-opacity", 0.6)
        .attr("strokeWidth", 2);

      // Create link labels
      const linkLabel = g
        .selectAll<SVGTextElement, GraphLink>(".link-label")
        .data(links)
        .join("text")
        .attr("class", "link-label")
        .attr("text-anchor", "middle")
        .attr("font-size", "10px")
        .attr("fill", "#9ca3af")
        .text((d: GraphLink) => d.relationship.replace(/_/g, " "));

      // Create node groups
      const nodeGroup = g
        .selectAll<SVGGElement, GraphNode>(".node-group")
        .data(nodes)
        .join("g")
        .attr("class", "node-group")
        .style("cursor", "pointer")
        .call(
          d3
            .drag<SVGGElement, GraphNode>()
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
        .attr("r", (d: GraphNode) => d.size)
        .attr("fill", (d: GraphNode) => colorScale(d.group))
        .attr("stroke", "#1f2937")
        .attr("strokeWidth", 2);

      // Add clipPath for user image
      const defs = svg.append("defs");
      defs
        .append("clipPath")
        .attr("id", "user-avatar-clip")
        .append("circle")
        .attr("r", 25); // Smaller radius for padding effect

      // Add background circle for user node
      nodeGroup
        .filter((d) => d.type === "user")
        .append("circle")
        .attr("r", 32)
        .attr("fill", "#27272a"); // zinc-800

      // Add image for user node
      const userProfilePic =
        user?.profilePicture ||
        "https://links.aryanranderiya.com/l/default_user";
      nodeGroup
        .filter((d) => d.type === "user")
        .append("image")
        .attr("xlink:href", userProfilePic)
        .attr("x", -25)
        .attr("y", -25)
        .attr("width", 50)
        .attr("height", 50)
        .attr("clip-path", "url(#user-avatar-clip)")
        .attr("preserveAspectRatio", "xMidYMid slice");

      // Add border circle for user node
      nodeGroup
        .filter((d) => d.type === "user")
        .append("circle")
        .attr("r", 32)
        .attr("fill", "none")
        .attr("stroke", "#00bbff")
        .attr("strokeWidth", 2);

      // Create node labels (for non-user nodes only)
      nodeGroup
        .filter((d) => d.type !== "user")
        .append("text")
        .attr("class", "node-label")
        .attr("text-anchor", "middle")
        .attr("dy", ".35em")
        .attr("font-size", "12px")
        .attr("font-weight", "500")
        .attr("fill", "#f9fafb")
        .attr("pointer-events", "none")
        .text((d: GraphNode) =>
          d.label.length > 20 ? `${d.label.substring(0, 17)}...` : d.label,
        );

      // Add event handlers
      nodeGroup
        .on("click", (_event, d) => {
          setSelectedNode(d);
          onNodeClick?.(d);
        })
        .on("mouseover", (event, d) => {
          const [x, y] = d3.pointer(event, container);
          const content = getNodeTooltipContent(d);

          setTooltip({
            x: x + 10,
            y: y - 10,
            content,
            visible: true,
          });
        })
        .on("mouseout", () => {
          setTooltip((prev) => ({ ...prev, visible: false }));
        });

      // Update positions on simulation tick
      simulation.on("tick", () => {
        link
          .attr("x1", (d: GraphLink) => (d.source as GraphNode).x!)
          .attr("y1", (d: GraphLink) => (d.source as GraphNode).y!)
          .attr("x2", (d: GraphLink) => (d.target as GraphNode).x!)
          .attr("y2", (d: GraphLink) => (d.target as GraphNode).y!);

        linkLabel
          .attr(
            "x",
            (d: GraphLink) =>
              ((d.source as GraphNode).x! + (d.target as GraphNode).x!) / 2,
          )
          .attr(
            "y",
            (d: GraphLink) =>
              ((d.source as GraphNode).y! + (d.target as GraphNode).y!) / 2,
          );

        nodeGroup.attr(
          "transform",
          (d: GraphNode) => `translate(${d.x},${d.y})`,
        );
      });

      // Cleanup function
      return () => {
        simulation.stop();
      };
    }, [memories, relations, onNodeClick, user?.profilePicture]);

    return (
      <div className={`relative h-full w-full ${className}`}>
        <div ref={containerRef} className="h-full w-full">
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
                <div className="text-xs text-zinc-100">{tooltip.content}</div>
              </CardBody>
            </Card>
          </div>
        )}

        {legendItems.length > 0 && (
          <div className="absolute top-4 right-4 z-10">
            <Card className="border border-zinc-600 bg-zinc-800/90 backdrop-blur-sm">
              <CardBody className="p-3">
                <div className="max-h-100 space-y-1 overflow-y-auto">
                  {legendItems.map((item) => (
                    <div
                      key={item.color + item.type}
                      className="flex items-center gap-2"
                    >
                      <div
                        className="h-3 w-3 rounded-full"
                        style={{ backgroundColor: item.color }}
                      />
                      <span className="text-xs text-zinc-300">{item.type}</span>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>
          </div>
        )}
      </div>
    );
  },
);

MemoryGraph.displayName = "MemoryGraph";

export default MemoryGraph;
