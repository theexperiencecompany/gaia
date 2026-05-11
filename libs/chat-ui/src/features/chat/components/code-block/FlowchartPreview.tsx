import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  Download01Icon,
  MoveIcon,
  RedoIcon,
  ZoomInAreaIcon,
  ZoomOutAreaIcon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

// Mermaid SDK init lives here (instead of CodeBlock) so the SDK is only
// pulled into the bundle when this component is actually rendered. Combined
// with FlowchartPreview being imported via `dynamic({ ssr: false })`, this
// keeps mermaid (~1.3 MB) out of the SSR/Cloudflare-Worker bundle entirely.
interface MermaidInstance {
  initialize: (config: object) => void;
  contentLoaded: () => void;
}
let mermaidInstance: MermaidInstance | null = null;
let mermaidInitPromise: Promise<MermaidInstance> | null = null;
function getMermaidInstance(): Promise<MermaidInstance> {
  if (mermaidInstance) return Promise.resolve(mermaidInstance);
  if (mermaidInitPromise) return mermaidInitPromise;
  mermaidInitPromise = import("mermaid").then((mod) => {
    mod.default.initialize({
      startOnLoad: true,
      theme: "dark",
      flowchart: { useMaxWidth: true, htmlLabels: true, curve: "linear" },
      gantt: { useMaxWidth: false },
      journey: { useMaxWidth: false },
      timeline: { useMaxWidth: false },
      elk: { mergeEdges: false },
    });
    mermaidInstance = mod.default;
    return mermaidInstance;
  });
  return mermaidInitPromise;
}

interface FlowchartPreviewProps {
  children: React.ReactNode;
}

const FlowchartPreview: React.FC<FlowchartPreviewProps> = ({ children }) => {
  const mermaidRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1.5);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(false);
  const startPositionRef = useRef({ x: 0, y: 0 });

  // Load mermaid SDK once on mount and re-render the diagram when content
  // changes. This used to live in CodeBlock.tsx, which forced the mermaid
  // module into every server render.
  useEffect(() => {
    let cancelled = false;
    getMermaidInstance().then((m) => {
      if (cancelled) return;
      m.contentLoaded();
    });
    return () => {
      cancelled = true;
    };
  }, [children]);

  const handleZoomIn = () => setScale((prev) => Math.min(prev + 0.1, 10));
  const handleZoomOut = () => setScale((prev) => Math.max(prev - 0.1, 0.5));
  const resetZoom = () => setScale(1.5);
  const resetPan = () => setPosition({ x: 0, y: 0 });

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDraggingRef.current = true;
    setIsDragging(true);
    setPosition((prev) => {
      startPositionRef.current = {
        x: e.clientX - prev.x,
        y: e.clientY - prev.y,
      };
      return prev;
    });
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isDraggingRef.current) {
      setPosition({
        x: e.clientX - startPositionRef.current.x,
        y: e.clientY - startPositionRef.current.y,
      });
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false;
    setIsDragging(false);
  }, []);

  const handleDownload = () => {
    if (!mermaidRef.current) return;

    const svgData = new XMLSerializer().serializeToString(
      mermaidRef.current.querySelector("svg")!,
    );
    const svgBlob = new Blob([svgData], {
      type: "image/svg+xml;charset=utf-8",
    });
    const svgUrl = URL.createObjectURL(svgBlob);
    const downloadLink = document.createElement("a");

    downloadLink.href = svgUrl;
    downloadLink.download = "mermaid-diagram.svg";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);
  };

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY * -0.01;
    setScale((prevScale) => Math.min(Math.max(prevScale + delta, 0.5), 10));
  }, []);

  useEffect(() => {
    const element = mermaidRef.current;

    if (element) {
      element.addEventListener("wheel", handleWheel, { passive: false });

      return () => {
        element.removeEventListener("wheel", handleWheel);
      };
    }
  }, [handleWheel]);

  return (
    <div className="relative h-[50vh] overflow-hidden bg-white p-4">
      <div
        className={`absolute top-0 left-0 h-full w-full ${isDragging ? "cursor-grabbing" : "cursor-grab"}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <div
          ref={mermaidRef}
          className="mermaid absolute select-none"
          style={{
            transform: `scale(${scale}) translate(${position.x}px, ${position.y}px)`,
            transformOrigin: "0 0",
            // cursor: isDragging ? "grabbing" : "grab",
          }}
        >
          {String(children).replace(/\n$/, "")}
        </div>
      </div>
      <div className="absolute right-2 bottom-2 flex flex-col items-center gap-1">
        <Tooltip content="Zoom Out">
          <Button size="sm" onPress={handleZoomOut} isIconOnly>
            <ZoomOutAreaIcon size={18} />
          </Button>
        </Tooltip>
        <Tooltip content="Reset Zoom">
          <Button size="sm" onPress={resetZoom} isIconOnly>
            <RedoIcon width={18} height={18} />
          </Button>
        </Tooltip>
        <Tooltip content="Zoom In">
          <Button size="sm" onPress={handleZoomIn} isIconOnly>
            <ZoomInAreaIcon size={18} />
          </Button>
        </Tooltip>

        <Tooltip content="Reset Pan & Zoom">
          <Button
            size="sm"
            onPress={() => {
              resetPan();
              resetZoom();
            }}
            isIconOnly
          >
            <MoveIcon size={18} />
          </Button>
        </Tooltip>

        <Tooltip content="Download Flowchart (.svg)">
          <Button size="sm" onPress={handleDownload} isIconOnly>
            <Download01Icon size={18} />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
};

export default FlowchartPreview;
