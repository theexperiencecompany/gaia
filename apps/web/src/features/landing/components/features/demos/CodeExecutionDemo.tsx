"use client";

import { Tick01Icon } from "@icons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const CODE_EXECUTION_TOOLS: ToolStep[] = [
  {
    category: "e2b",
    name: "execute_code",
    message: `import pandas as pd
df = pd.read_csv("sales.csv")
top = df.groupby("region").sum().sort_values(ascending=False)
print(top.head(3))`,
  },
];

// ─── Code Output Card ─────────────────────────────────────────────────────────

const OUTPUT_ROWS = [
  { region: "North America", value: "$2.4M", up: true },
  { region: "Europe", value: "$1.8M", up: true },
  { region: "APAC", value: "$1.1M", up: false },
];

function CodeOutputCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-emerald-400/10">
          <span className="text-[9px] font-bold text-emerald-400">e2b</span>
        </div>
        <span className="text-[11px] font-medium text-zinc-400">
          execute_code
        </span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-400">
          <Tick01Icon height={12} />
          done in 1.2s
        </span>
      </div>

      {/* Code panel */}
      <div className="mb-2 rounded-2xl bg-zinc-900 p-3 font-mono text-[11px] leading-relaxed">
        <div>
          <span className="text-blue-400">import</span>{" "}
          <span className="text-zinc-300">pandas</span>{" "}
          <span className="text-blue-400">as</span>{" "}
          <span className="text-zinc-300">pd</span>
        </div>
        <div className="mt-1">
          <span className="text-zinc-300">df</span>{" "}
          <span className="text-zinc-500">=</span>{" "}
          <span className="text-zinc-300">pd</span>
          <span className="text-zinc-500">.</span>
          <span className="text-amber-400">read_csv</span>
          <span className="text-zinc-500">(</span>
          <span className="text-emerald-400">"sales.csv"</span>
          <span className="text-zinc-500">)</span>
        </div>
        <div>
          <span className="text-zinc-300">top</span>{" "}
          <span className="text-zinc-500">=</span>{" "}
          <span className="text-zinc-300">df</span>
          <span className="text-zinc-500">.</span>
          <span className="text-amber-400">groupby</span>
          <span className="text-zinc-500">(</span>
          <span className="text-emerald-400">"region"</span>
          <span className="text-zinc-500">).</span>
          <span className="text-amber-400">sum</span>
          <span className="text-zinc-500">().</span>
          <span className="text-amber-400">sort_values</span>
          <span className="text-zinc-500">(</span>
          <span className="text-amber-400">ascending</span>
          <span className="text-zinc-500">=</span>
          <span className="text-blue-400">False</span>
          <span className="text-zinc-500">)</span>
        </div>
        <div>
          <span className="text-amber-400">print</span>
          <span className="text-zinc-500">(</span>
          <span className="text-zinc-300">top</span>
          <span className="text-zinc-500">.</span>
          <span className="text-amber-400">head</span>
          <span className="text-zinc-500">(</span>
          <span className="text-purple-400">3</span>
          <span className="text-zinc-500">))</span>
        </div>
      </div>

      {/* Output panel */}
      <div className="space-y-1 rounded-2xl bg-zinc-900 p-3 font-mono text-[11px]">
        <div className="mb-1 flex items-center justify-between text-[10px] text-zinc-500">
          <span>region</span>
          <span>revenue</span>
        </div>
        {OUTPUT_ROWS.map((row) => (
          <div key={row.region} className="flex items-center justify-between">
            <span className="text-zinc-300">{row.region}</span>
            <span className={row.up ? "text-emerald-400" : "text-zinc-400"}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Messages ─────────────────────────────────────────────────────────────────

const CODE_EXECUTION_MESSAGES: ChatMessage[] = [
  {
    id: "ce1",
    role: "user",
    content: "Summarize regional sales from sales.csv",
  },
  {
    id: "ce2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "ce3",
    role: "tools",
    content: "",
    tools: CODE_EXECUTION_TOOLS,
    delay: 900,
  },
  {
    id: "ce4",
    role: "card",
    content: "",
    cardContent: <CodeOutputCard />,
    delay: 500,
  },
  {
    id: "ce5",
    role: "assistant",
    content:
      "North America leads at $2.4M, followed by Europe at $1.8M. APAC is third at $1.1M — solid growth but still a gap to close.",
    delay: 700,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function CodeExecutionDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={CODE_EXECUTION_MESSAGES} minHeight={260} />
    </div>
  );
}
