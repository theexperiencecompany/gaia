"use client";

import { Tooltip } from "@heroui/tooltip";
import { ArrowRight02Icon, Cancel01Icon, Tick02Icon } from "@icons";
import Image from "next/image";
import { Link } from "@/i18n/navigation";

import LargeHeader from "../shared/LargeHeader";

type CellValue =
  | { type: "yes" }
  | { type: "no" }
  | { type: "partial"; label: string }
  | { type: "text"; label: string };

interface CompetitorInfo {
  name: string;
  slug: string | null;
  logo: { type: "image"; src: string } | { type: "letter"; char: string };
}

const COMPETITORS: CompetitorInfo[] = [
  {
    name: "GAIA",
    slug: null,
    logo: { type: "image", src: "/brand/gaia_logo.png" },
  },
  {
    name: "OpenClaw",
    slug: "openclaw",
    logo: { type: "image", src: "/images/icons/openclaw.svg" },
  },
  {
    name: "Poke",
    slug: "poke",
    logo: { type: "image", src: "/images/icons/poke.png" },
  },
  {
    name: "ChatGPT",
    slug: "chatgpt",
    logo: { type: "image", src: "/images/icons/chatgpt.webp" },
  },
  {
    name: "Claude",
    slug: "claude",
    logo: { type: "image", src: "https://cdn.simpleicons.org/claude/D97757" },
  },
  {
    name: "Gemini",
    slug: "gemini",
    logo: { type: "image", src: "/images/icons/gemini.webp" },
  },
];

interface GridRow {
  feature: string;
  values: [CellValue, CellValue, CellValue, CellValue, CellValue, CellValue];
}

const GRID_ROWS: GridRow[] = [
  {
    feature: "Acts before you ask",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
    ],
  },
  {
    feature: "WhatsApp / Slack / Telegram",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
    ],
  },
  {
    feature: "Mobile + Desktop app",
    values: [
      { type: "yes" },
      { type: "partial", label: "CLI" },
      { type: "no" },
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
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
      { type: "no" },
    ],
  },
  {
    feature: "Zero Technical Setup",
    values: [
      { type: "yes" },
      { type: "no" },
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
    ],
  },
  {
    feature: "Multi-step workflows",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "partial", label: "Basic recipes" },
      { type: "no" },
      { type: "yes" },
      { type: "no" },
    ],
  },
  {
    feature: "Automated todo list",
    values: [
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
    ],
  },
  {
    feature: "Community integration marketplace",
    values: [
      { type: "yes" },
      { type: "yes" },
      { type: "yes" },
      { type: "no" },
      { type: "no" },
      { type: "no" },
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
      { type: "text", label: "50+ + 100 skills" },
      { type: "text", label: "~10 services + MCP" },
      { type: "no" },
      { type: "text", label: "MCP connectors" },
      { type: "no" },
    ],
  },
];

function BrandLogo({ competitor }: { competitor: CompetitorInfo }) {
  if (competitor.logo.type === "image") {
    return (
      <div className="relative h-7 w-7 overflow-hidden rounded-md">
        <Image
          src={competitor.logo.src}
          alt={competitor.name}
          fill
          className="object-contain p-0.5"
          sizes="28px"
          unoptimized
        />
      </div>
    );
  }
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-700 text-xs font-semibold text-zinc-200">
      {competitor.logo.char}
    </div>
  );
}

function Cell({ value }: { value: CellValue }) {
  if (value.type === "yes") {
    return <Tick02Icon width={18} className="mx-auto text-emerald-400" />;
  }
  if (value.type === "no") {
    return <Cancel01Icon width={18} className="mx-auto text-zinc-700" />;
  }
  if (value.type === "partial") {
    return (
      <span className="text-[11px] leading-snug text-amber-400/90">
        {value.label}
      </span>
    );
  }
  return (
    <span className="text-[11px] leading-snug text-zinc-300">
      {value.label}
    </span>
  );
}

export default function ComparisonGrid() {
  return (
    <section className="flex w-full flex-col items-center px-4 pb-24 sm:px-6 sm:pb-32 lg:px-8">
      <div className="flex w-full max-w-6xl flex-col items-center gap-10">
        <LargeHeader
          headingText="Your chatbot doesn't do this."
          subHeadingText="Everything ChatGPT does. Plus everything it doesn't."
          centered
        />

        <div className="w-full overflow-x-auto rounded-3xl bg-gradient-to-b from-zinc-900 to-zinc-950 outline outline-1 outline-zinc-900">
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr>
                <th className="w-[200px] px-5 py-3 text-left text-xs font-medium uppercase tracking-widest text-zinc-500">
                  Feature
                </th>
                {COMPETITORS.map((c) => (
                  <th
                    key={c.name}
                    className={`px-5 py-3 text-center align-middle ${
                      c.slug === null ? "bg-primary/5" : ""
                    }`}
                  >
                    <Tooltip content={c.name} placement="top">
                      {c.slug ? (
                        <Link
                          href={`/compare/${c.slug}`}
                          aria-label={`Compare with ${c.name}`}
                          className="inline-flex transition-transform hover:scale-110"
                        >
                          <BrandLogo competitor={c} />
                        </Link>
                      ) : (
                        <span className="inline-flex">
                          <BrandLogo competitor={c} />
                        </span>
                      )}
                    </Tooltip>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {GRID_ROWS.map((row, i) => (
                <tr
                  key={row.feature}
                  className={`border-t border-zinc-800/60 ${
                    i % 2 === 0 ? "bg-transparent" : "bg-zinc-900/40"
                  }`}
                >
                  <td className="p-5 text-xs font-medium text-zinc-300">
                    {row.feature}
                  </td>
                  {row.values.map((value, j) => (
                    <td
                      key={COMPETITORS[j]?.name ?? `cell-${j}`}
                      className={`p-5 text-center align-middle ${
                        COMPETITORS[j]?.slug === null ? "bg-primary/5" : ""
                      }`}
                    >
                      <Cell value={value} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-center text-xs text-zinc-500">
          Sourced from official websites and documentation.{" "}
          <Link
            href="/compare"
            className="inline-flex items-center gap-1 underline underline-offset-2 transition-colors hover:text-zinc-300"
          >
            See full comparisons
            <ArrowRight02Icon width={12} height={12} />
          </Link>
        </p>
      </div>
    </section>
  );
}
