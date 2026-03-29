"use client";

import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const CODE_EXECUTION_TOOLS: ToolStep[] = [
  {
    category: "e2b",
    name: "execute_code",
    message: `import matplotlib.pyplot as plt
months = ['Jan', 'Feb', 'Mar']
sales = [42000, 61000, 58000]
plt.bar(months, sales, color='#00bbff')
plt.title('Q1 Sales')
plt.show()`,
  },
];

// ─── Chart Card ───────────────────────────────────────────────────────────────

const BAR_DATA = [
  { label: "Jan", value: 42000, height: 77 },
  { label: "Feb", value: 61000, height: 112 },
  { label: "Mar", value: 58000, height: 107 },
];

function Q1SalesChartCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="mb-3 text-sm font-semibold text-zinc-100">Q1 Sales</p>
      <div className="rounded-2xl bg-zinc-900 p-3">
        <div className="relative flex h-28 items-end gap-4 px-2">
          {BAR_DATA.map((bar) => (
            <div
              key={bar.label}
              className="flex flex-1 flex-col items-center justify-end h-full gap-1"
            >
              <span className="text-[10px] font-medium text-zinc-400">
                ${(bar.value / 1000).toFixed(0)}k
              </span>
              <div
                className="w-full rounded-t-md"
                style={{
                  height: bar.height,
                  backgroundColor: "#00bbff",
                  opacity: 0.85,
                }}
              />
              <span className="text-xs text-zinc-500">{bar.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Messages ─────────────────────────────────────────────────────────────────

const CODE_EXECUTION_MESSAGES: ChatMessage[] = [
  {
    id: "ce1",
    role: "user",
    content: "Plot my sales data for Q1 as a bar chart",
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
    cardContent: <Q1SalesChartCard />,
    delay: 500,
  },
  {
    id: "ce5",
    role: "assistant",
    content:
      "February was your strongest month at $61k. March held steady at $58k. January was the lowest at $42k — likely seasonality.",
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
