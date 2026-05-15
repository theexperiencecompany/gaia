"use client";

import { TOOL_FIXTURES } from "@shared/chat";
import Link from "next/link";
import type { JSX } from "react";

export default function ToolGalleryPage(): JSX.Element {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-zinc-100">
          Tool Card Gallery
        </h1>
        <p className="mt-2 text-sm text-zinc-400">
          Select a tool to preview it in isolation. Compare with mobile at{" "}
          <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
            gaia://tool-gallery/[toolName]
          </code>
          .
        </p>
      </div>
      <div className="grid w-full max-w-2xl grid-cols-2 gap-2">
        {TOOL_FIXTURES.map((fixture) => (
          <Link
            key={fixture.toolName}
            href={`/dev/tool-gallery/${fixture.toolName}`}
            className="rounded-xl bg-zinc-900 px-4 py-3 transition-colors hover:bg-zinc-800"
          >
            <p className="text-sm font-medium text-zinc-200">{fixture.label}</p>
            <p className="mt-0.5 font-mono text-[10px] text-zinc-500">
              {fixture.toolName}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
