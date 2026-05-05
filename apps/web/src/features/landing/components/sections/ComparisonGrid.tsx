"use client";

import { Cancel01Icon, Tick02Icon } from "@icons";
import Link from "next/link";
import LargeHeader from "../shared/LargeHeader";

type CellValue =
  | { type: "yes" }
  | { type: "no" }
  | { type: "partial"; label: string }
  | { type: "text"; label: string };

interface CompetitorInfo {
  name: string;
  slug: string | null; // null for GAIA
}

const COMPETITORS: CompetitorInfo[] = [
  { name: "GAIA", slug: null },
  { name: "OpenClaw", slug: "openclaw" },
  { name: "Poke", slug: "poke" },
  { name: "ChatGPT", slug: "chatgpt" },
  { name: "Claude", slug: "claude" },
  { name: "Gemini", slug: "gemini" },
];

interface GridRow {
  feature: string;
  values: [CellValue, CellValue, CellValue, CellValue, CellValue, CellValue]; // [GAIA, OpenClaw, Poke, ChatGPT, Claude, Gemini]
}

const GRID_ROWS: GridRow[] = [
  {
    feature: "Acts before you ask",
    values: [
      { type: "yes" },
      { type: "partial", label: "Advanced, more mature workflow system" },
      { type: "partial", label: "Inbox/calendar monitoring via SMS" },
      { type: "partial", label: "10 scheduled reminders, user-triggered" },
      { type: "no" },
      { type: "partial", label: "Rolling out in 2026" },
    ],
  },
  {
    feature: "WhatsApp / Slack / Telegram",
    values: [
      { type: "yes" },
      { type: "no" },
      { type: "partial", label: "Telegram + iMessage/SMS only" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
    ],
  },
  {
    feature: "Mobile + Desktop app",
    values: [
      { type: "yes" },
      { type: "partial", label: "Desktop only (Mac/Win)" },
      { type: "partial", label: "SMS/iMessage, no app" },
      { type: "partial", label: "Mobile + Web, no Linux" },
      { type: "partial", label: "Mobile + Web, no Linux" },
      { type: "partial", label: "Mobile + Desktop (no Linux)" },
    ],
  },
  {
    feature: "Open source + self-host",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
      {
        type: "partial",
        label: "Gemma models open-weight; product is cloud-only",
      },
    ],
  },
  {
    feature: "Multi-step scheduled workflows",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "partial", label: "Basic automation recipes" },
      { type: "partial", label: "Operator-level agents, no cron" },
      { type: "partial", label: "Cowork multi-step, no cron" },
      { type: "partial", label: "Workspace Flows (enterprise)" },
    ],
  },
  {
    feature: "Cross-tool persistent memory",
    values: [
      { type: "yes" },
      { type: "partial", label: "Session memory, no cross-tool graph" },
      { type: "no" },
      { type: "partial", label: "3-layer memory system" },
      { type: "partial", label: "Projects memory (since 2026)" },
      { type: "partial", label: "Google data only" },
    ],
  },
  {
    feature: "Unified view (tasks + email + calendar)",
    values: [
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
      { type: "partial", label: "Google Workspace only" },
    ],
  },
  {
    feature: "Integrations",
    values: [
      { type: "text", label: "50+ native + MCP" },
      { type: "text", label: "50+ + 100 community skills" },
      { type: "text", label: "~10 core services" },
      { type: "text", label: "1000+ via GPT plugins — widest selection" },
      { type: "text", label: "MCP, Claude.ai connectors" },
      { type: "text", label: "Google ecosystem native" },
    ],
  },
];

function Cell({ value }: { value: CellValue }) {
  if (value.type === "yes") {
    return <Tick02Icon width={16} className="text-emerald-400 mx-auto" />;
  }
  if (value.type === "no") {
    return <Cancel01Icon width={16} className="text-zinc-600 mx-auto" />;
  }
  if (value.type === "partial") {
    return (
      <span className="text-amber-400 text-xs leading-snug">{value.label}</span>
    );
  }
  return (
    <span className="text-zinc-300 text-xs leading-snug">{value.label}</span>
  );
}

export default function ComparisonGrid() {
  return (
    <section className="flex w-full flex-col items-center px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center gap-10">
        <LargeHeader headingText="How GAIA compares" centered />

        <div className="w-full overflow-x-auto rounded-2xl outline outline-1 outline-zinc-800">
          <table className="w-full min-w-[640px] border-collapse">
            <thead>
              <tr className="border-b border-zinc-800">
                <th className="p-4 text-left text-sm font-medium text-zinc-400 w-[180px]">
                  Feature
                </th>
                {COMPETITORS.map((c) => (
                  <th
                    key={c.name}
                    className={`p-4 text-center text-sm font-semibold ${c.slug === null ? "text-primary" : "text-zinc-300"}`}
                  >
                    {c.slug === null ? (
                      c.name
                    ) : (
                      <Link
                        href={`/compare/${c.slug}`}
                        className="hover:text-zinc-100 transition-colors"
                      >
                        {c.name}
                      </Link>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {GRID_ROWS.map((row, i) => (
                <tr
                  key={row.feature}
                  className={`border-b border-zinc-800/50 ${i % 2 === 0 ? "bg-zinc-900" : "bg-zinc-950"}`}
                >
                  <td className="p-4 text-xs font-medium text-zinc-300">
                    {row.feature}
                  </td>
                  {row.values.map((value, j) => (
                    <td
                      key={COMPETITORS[j]?.name ?? j}
                      className={`p-4 text-center align-middle ${COMPETITORS[j]?.slug === null ? "bg-primary/5" : ""}`}
                    >
                      <Cell value={value} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-zinc-500 text-center">
          Data sourced from official websites and documentation. Last updated
          May 2026.{" "}
          <Link
            href="/compare/chatgpt"
            className="underline underline-offset-2 hover:text-zinc-300 transition-colors"
          >
            See full comparisons
          </Link>
        </p>
      </div>
    </section>
  );
}
