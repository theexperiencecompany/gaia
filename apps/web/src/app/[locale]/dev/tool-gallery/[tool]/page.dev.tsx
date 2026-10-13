"use client";

import { TOOL_FIXTURES } from "@shared/chat";
import { useParams } from "next/navigation";
import type { JSX } from "react";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import GalleryToolCard from "./GalleryToolCard";

export default function ToolPage(): JSX.Element {
  const params = useParams();
  const toolName = params?.tool as string;
  const fixture = TOOL_FIXTURES.find((f) => f.toolName === toolName);

  if (!fixture) {
    return (
      <div className="flex-1 overflow-y-auto px-8 py-8">
        <p className="text-sm text-zinc-500">
          Unknown tool:{" "}
          <span className="font-mono text-zinc-400">{toolName}</span>
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">{fixture.label}</h1>
        <p className="mt-1 text-xs text-zinc-500">
          <span className="font-mono">{fixture.toolName}</span>
          {" · "}
          {fixture.description}
        </p>
      </div>
      <ErrorBoundary>
        <GalleryToolCard fixture={fixture} />
      </ErrorBoundary>
    </div>
  );
}
