"use client";

import {
  ArrowRight02Icon,
  CheckmarkCircle02Icon,
  ConnectIcon,
  DiscordIcon,
  Globe02Icon,
  MapsIcon,
  Search01Icon,
  StarIcon,
  WorkflowSquare10Icon,
  ZapIcon,
} from "@icons";
import Image from "next/image";
import { useState } from "react";
import { ChevronDown, Github } from "@/components/shared/icons";
import { cn } from "@/lib/utils";

/* ────────────────────────────────────────────────────────────────────────── */
/* Wallpaper map — real GAIA assets                                            */
/* ────────────────────────────────────────────────────────────────────────── */

const wp = {
  staircase: "/images/wallpapers/staircase.webp",
  library: "/images/wallpapers/library.webp",
  mesh: "/images/wallpapers/mesh_gradient_1.webp",
  swiss: "/images/wallpapers/swiss.webp",
  swissDay: "/images/wallpapers/swiss kid day.webp",
  swissEvening: "/images/wallpapers/swiss kid evening.webp",
  swissNight: "/images/wallpapers/swiss kid night.webp",
  swissMorning: "/images/wallpapers/swiss kid morning.webp",
  sfNight: "/images/wallpapers/sf_night.webp",
  space: "/images/wallpapers/space.webp",
  northernLights: "/images/wallpapers/northernlights.webp",
  surreal: "/images/wallpapers/surreal.webp",
  landscape: "/images/wallpapers/landscape.webp",
  field: "/images/wallpapers/field.webp",
  switzerlandNight: "/images/wallpapers/switzerland_night.webp",
  switzerlandMac: "/images/wallpapers/switzerland_mac.webp",
} as const;

/* ────────────────────────────────────────────────────────────────────────── */
/* BentoCard — Featurebase-style image card                                    */
/* ────────────────────────────────────────────────────────────────────────── */

function BentoCard({
  href = "#",
  src,
  title,
  desc,
  className,
  badge,
  IconComp,
}: {
  href?: string;
  src: string;
  title: string;
  desc?: string;
  className?: string;
  badge?: string;
  IconComp?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <a
      href={href}
      className={cn(
        "group relative overflow-hidden rounded-2xl bg-zinc-900 transition-all duration-300",
        className,
      )}
    >
      <Image
        src={src}
        alt=""
        fill
        sizes="(max-width: 768px) 100vw, 30vw"
        className="object-cover transition-transform duration-700 group-hover:scale-105"
      />
      <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/55 to-black/10" />
      <div className="absolute inset-0 p-5 flex flex-col justify-end">
        {(badge || IconComp) && (
          <div className="flex items-center gap-2 mb-auto">
            {IconComp && (
              <div className="flex size-9 items-center justify-center rounded-xl bg-white/10 backdrop-blur-md text-white">
                <IconComp className="size-5" />
              </div>
            )}
            {badge && (
              <span className="rounded-full bg-white/10 backdrop-blur-md px-2.5 py-1 text-[10px] font-medium uppercase tracking-widest text-white">
                {badge}
              </span>
            )}
          </div>
        )}
        <div>
          <div className="text-[15px] font-semibold text-white leading-tight">
            {title}
          </div>
          {desc && (
            <div className="mt-1 text-xs text-white/70 leading-snug max-w-[90%]">
              {desc}
            </div>
          )}
        </div>
      </div>
    </a>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Floater — centered floating dropdown panel (Featurebase pattern)            */
/* ────────────────────────────────────────────────────────────────────────── */

function Floater({
  children,
  width = 1100,
}: {
  children: React.ReactNode;
  width?: number;
}) {
  return (
    <div
      className="absolute left-1/2 top-full z-40 -translate-x-1/2 pt-3"
      style={{ width }}
    >
      <div className="rounded-3xl bg-zinc-950/95 backdrop-blur-2xl shadow-[0_30px_120px_rgba(0,0,0,0.6)] p-3 animate-in fade-in zoom-in-95 duration-200">
        {children}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* P1 — Featurebase-style 4×2 bento (2 tall + 4 medium)                        */
/* ────────────────────────────────────────────────────────────────────────── */

function P1_Bento() {
  return (
    <Floater>
      <div className="grid grid-cols-4 grid-rows-2 gap-3 h-[440px]">
        <BentoCard
          src={wp.staircase}
          title="Use Cases"
          desc="80+ ready-to-run workflows. Fork any and edit in plain English."
          className="row-span-2"
          IconComp={WorkflowSquare10Icon}
          href="/use-cases"
        />
        <BentoCard
          src={wp.library}
          title="Marketplace"
          desc="Community integrations, agents, and tools. Install in one click."
          className="row-span-2"
          IconComp={ConnectIcon}
          href="/marketplace"
        />
        <BentoCard
          src={wp.mesh}
          title="Features"
          desc="Voice, workflows, memory, and 50+ tools."
          IconComp={ZapIcon}
          href="/features"
        />
        <BentoCard
          src={wp.space}
          title="Roadmap"
          desc="What's coming next."
          IconComp={MapsIcon}
          href="/roadmap"
        />
        <BentoCard
          src={wp.swissDay}
          title="For your role"
          desc="Founders, devs, sales, PMs, and more."
          IconComp={StarIcon}
          href="/for"
        />
        <BentoCard
          src={wp.switzerlandMac}
          title="Download"
          desc="Mac, iOS, Android, CLI."
          IconComp={Globe02Icon}
          href="/download"
        />
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* P2 — Hero workflow + supporting bento                                       */
/* ────────────────────────────────────────────────────────────────────────── */

function P2_Hero() {
  return (
    <Floater>
      <div className="grid grid-cols-12 grid-rows-2 gap-3 h-[440px]">
        <BentoCard
          src={wp.northernLights}
          title="Inbox Zero in 5 minutes a day"
          desc="The most-forked GAIA workflow. Triage 100+ emails by texting GAIA."
          className="col-span-6 row-span-2"
          badge="Workflow of the week"
        />
        <BentoCard
          src={wp.staircase}
          title="Use Cases"
          desc="80+ workflows you can fork."
          className="col-span-3"
          IconComp={WorkflowSquare10Icon}
          href="/use-cases"
        />
        <BentoCard
          src={wp.library}
          title="Marketplace"
          desc="Community integrations."
          className="col-span-3"
          IconComp={ConnectIcon}
          href="/marketplace"
        />
        <BentoCard
          src={wp.mesh}
          title="Features"
          desc="Voice, workflows, memory."
          className="col-span-3"
          IconComp={ZapIcon}
          href="/features"
        />
        <BentoCard
          src={wp.swissDay}
          title="For your role"
          desc="Built for founders, devs, sales, PMs."
          className="col-span-3"
          IconComp={StarIcon}
          href="/for"
        />
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* P3 — Persona bento (3×2)                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

const personas = [
  {
    role: "Founders",
    desc: "Your AI chief of staff",
    src: wp.swissMorning,
    href: "/for/startup-founders",
  },
  {
    role: "Developers",
    desc: "Auto-summarize PRs + Linear",
    src: wp.sfNight,
    href: "/for/software-developers",
  },
  {
    role: "Sales",
    desc: "Auto-follow-up + CRM monitor",
    src: wp.surreal,
    href: "/for/sales-professionals",
  },
  {
    role: "Product Managers",
    desc: "Stakeholder digests + sprint reports",
    src: wp.staircase,
    href: "/for/product-managers",
  },
  {
    role: "Eng Managers",
    desc: "1:1 prep + sprint reports",
    src: wp.field,
    href: "/for/engineering-managers",
  },
  {
    role: "Agency Owners",
    desc: "Run 10 clients without losing your mind",
    src: wp.swissEvening,
    href: "/for/agency-owners",
  },
] as const;

function P3_Personas() {
  return (
    <Floater>
      <div className="grid grid-cols-3 grid-rows-2 gap-3 h-[440px]">
        {personas.map((p) => (
          <BentoCard
            key={p.role}
            src={p.src}
            title={p.role}
            desc={p.desc}
            href={p.href}
          />
        ))}
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* P4 — Switch from X (hero + 6 comparison tiles)                              */
/* ────────────────────────────────────────────────────────────────────────── */

const replaces = [
  { name: "ChatGPT", reason: "Plus actions, memory, tools" },
  { name: "Notion AI", reason: "Plus voice + scheduling" },
  { name: "Pi", reason: "Plus your data + your apps" },
  { name: "Zapier + GPT", reason: "One agent that just does it" },
  { name: "Motion", reason: "Plus the rest of your work" },
  { name: "Perplexity", reason: "Plus action — not just answers" },
] as const;

function P4_Switch() {
  return (
    <Floater>
      <div className="grid grid-cols-12 gap-3 h-[440px]">
        <BentoCard
          src={wp.switzerlandNight}
          title="Replace your stack"
          desc="One assistant. Voice, memory, workflows, 50+ tools — across every channel you use."
          className="col-span-5 row-span-2"
          badge="Switch to GAIA"
          href="/compare"
        />
        <div className="col-span-7 row-span-2 grid grid-cols-3 gap-2">
          {replaces.map((r) => (
            <a
              key={r.name}
              href={`/compare/${r.name.toLowerCase().replace(/\s+/g, "-")}`}
              className="group rounded-2xl bg-zinc-800 hover:bg-zinc-700 transition-all p-4 flex flex-col justify-between"
            >
              <div className="flex items-center gap-2 text-xs">
                <span className="text-zinc-500 line-through">{r.name}</span>
                <ArrowRight02Icon className="size-3 text-zinc-600" />
                <span className="text-primary font-medium">GAIA</span>
              </div>
              <div className="text-[13px] text-zinc-100 leading-snug mt-3">
                {r.reason}
              </div>
            </a>
          ))}
        </div>
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* R1 — Resources bento (Featurebase pattern)                                  */
/* ────────────────────────────────────────────────────────────────────────── */

function R1_Resources() {
  return (
    <Floater>
      <div className="grid grid-cols-12 grid-rows-2 gap-3 h-[440px]">
        <BentoCard
          src={wp.library}
          title="Documentation"
          desc="Guides, API reference, self-host. Everything to build with GAIA."
          className="col-span-5 row-span-2"
          IconComp={Search01Icon}
        />
        <BentoCard
          src={wp.northernLights}
          title="Status & releases"
          desc="All systems normal · v0.18 just shipped"
          className="col-span-7"
          badge="Live"
        />
        <BentoCard
          src={wp.sfNight}
          title="Community"
          desc="3,200 members on Discord. Open source on GitHub."
          className="col-span-4"
          IconComp={DiscordIcon}
        />
        <BentoCard
          src={wp.swissDay}
          title="Blog"
          desc="Engineering deep-dives and product writing."
          className="col-span-3"
        />
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* R2 — Live & compare                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

function R2_LiveCompare() {
  return (
    <Floater>
      <div className="grid grid-cols-12 grid-rows-2 gap-3 h-[440px]">
        <BentoCard
          src={wp.northernLights}
          title="All systems normal"
          desc="99.98% uptime · 30 days · v0.18 shipped 2 days ago"
          className="col-span-7 row-span-2"
          badge="Live"
        />
        <BentoCard
          src={wp.switzerlandNight}
          title="Compare"
          desc="GAIA vs ChatGPT, Notion AI, Pi, and 9 more."
          className="col-span-5"
          IconComp={CheckmarkCircle02Icon}
        />
        <BentoCard
          src={wp.space}
          title="Roadmap"
          desc="What's coming · Q2 2026"
          className="col-span-2"
          IconComp={MapsIcon}
        />
        <BentoCard
          src={wp.surreal}
          title="Manifesto"
          desc="Why we built GAIA"
          className="col-span-3"
        />
      </div>
    </Floater>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Variant registry                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

const productVariants = {
  P1: {
    name: "Bento 4×2",
    Comp: P1_Bento,
    blurb: "6 cards: 2 tall + 4 medium (Featurebase Solutions style)",
  },
  P2: {
    name: "Hero workflow",
    Comp: P2_Hero,
    blurb: "1 big featured workflow + 4 supporting cards",
  },
  P3: {
    name: "Personas 3×2",
    Comp: P3_Personas,
    blurb: "6 role cards, evocative imagery per persona",
  },
  P4: {
    name: "Switch from X",
    Comp: P4_Switch,
    blurb: "Hero pitch + 6 'replaces X' tiles",
  },
} as const;

const resourceVariants = {
  R1: {
    name: "Resources bento",
    Comp: R1_Resources,
    blurb: "Big docs hero + status + community + blog",
  },
  R2: {
    name: "Live & compare",
    Comp: R2_LiveCompare,
    blurb: "Big live status + compare + roadmap + manifesto",
  },
} as const;

type ProductKey = keyof typeof productVariants;
type ResourceKey = keyof typeof resourceVariants;

/* ────────────────────────────────────────────────────────────────────────── */
/* Page                                                                        */
/* ────────────────────────────────────────────────────────────────────────── */

export default function NavbarDemoClient() {
  const [productKey, setProductKey] = useState<ProductKey>("P1");
  const [resourceKey, setResourceKey] = useState<ResourceKey>("R1");
  const [open, setOpen] = useState<"product" | "resources" | null>(null);

  const ProductComp = productVariants[productKey].Comp;
  const ResourceComp = resourceVariants[resourceKey].Comp;

  return (
    <div className="min-h-screen bg-[#111111] text-zinc-100 relative overflow-x-hidden">
      <div
        className={cn(
          "fixed inset-0 z-30 bg-black/60 backdrop-blur-sm transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
      />

      <FakeLanding />

      <div
        className="fixed top-0 left-0 right-0 z-40 px-4 pt-4"
        onMouseLeave={() => setOpen(null)}
      >
        <div className="mx-auto max-w-6xl">
          <div className="relative flex h-14 items-center justify-between rounded-2xl bg-zinc-900/40 backdrop-blur-2xl px-3">
            <div className="flex items-center gap-2 px-2">
              <div className="size-7 rounded-md bg-gradient-to-br from-[#00bbff] to-[#0080ff]" />
              <span className="font-semibold">GAIA</span>
            </div>

            <div className="flex items-center gap-1 text-sm">
              <NavTab
                label="Product"
                hot={open === "product"}
                onHover={() => setOpen("product")}
              />
              <NavLink label="Pricing" />
              <NavLink label="About" />
              <NavTab
                label="Resources"
                hot={open === "resources"}
                onHover={() => setOpen("resources")}
              />
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                className="flex items-center gap-1.5 rounded-xl bg-black/60 px-3 h-9 text-xs"
              >
                <Github width={14} height={14} color="white" /> 2.4k
              </button>
              <button
                type="button"
                className="rounded-xl bg-[#00bbff] px-4 h-9 text-sm font-medium text-black"
              >
                Get Started
              </button>
            </div>

            {open === "product" && <ProductComp />}
            {open === "resources" && <ResourceComp />}
          </div>
        </div>
      </div>

      <Switcher
        productKey={productKey}
        resourceKey={resourceKey}
        onProduct={(k) => {
          setProductKey(k);
          setOpen("product");
        }}
        onResource={(k) => {
          setResourceKey(k);
          setOpen("resources");
        }}
      />
    </div>
  );
}

function NavTab({
  label,
  hot,
  onHover,
}: {
  label: string;
  hot: boolean;
  onHover: () => void;
}) {
  return (
    <button
      type="button"
      onMouseEnter={onHover}
      onFocus={onHover}
      className={cn(
        "flex h-9 items-center gap-1 rounded-xl px-4 text-sm transition",
        hot ? "bg-zinc-800 text-zinc-100" : "text-zinc-300 hover:text-zinc-100",
      )}
    >
      {label}{" "}
      <ChevronDown
        width={14}
        height={14}
        className={cn("transition", hot && "rotate-180")}
      />
    </button>
  );
}

function NavLink({ label }: { label: string }) {
  return (
    <span className="flex h-9 items-center px-4 text-sm text-zinc-300 hover:text-zinc-100 cursor-pointer">
      {label}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Switcher                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

function Switcher({
  productKey,
  resourceKey,
  onProduct,
  onResource,
}: {
  productKey: ProductKey;
  resourceKey: ResourceKey;
  onProduct: (k: ProductKey) => void;
  onResource: (k: ResourceKey) => void;
}) {
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
      <div className="rounded-2xl bg-zinc-900/95 backdrop-blur-xl shadow-2xl px-3 py-2.5 min-w-[600px]">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-medium uppercase tracking-widest text-zinc-500">
            Product
          </span>
          {(Object.keys(productVariants) as ProductKey[]).map((k) => (
            <button
              type="button"
              key={k}
              onMouseEnter={() => onProduct(k)}
              onClick={() => onProduct(k)}
              className={cn(
                "rounded-lg px-3 py-1 text-xs transition",
                productKey === k
                  ? "bg-[#00bbff] text-black font-medium"
                  : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700",
              )}
              title={productVariants[k].name}
            >
              {k}
            </button>
          ))}
          <div className="h-5 w-px bg-zinc-800 mx-1" />
          <span className="text-[10px] font-medium uppercase tracking-widest text-zinc-500">
            Resources
          </span>
          {(Object.keys(resourceVariants) as ResourceKey[]).map((k) => (
            <button
              type="button"
              key={k}
              onMouseEnter={() => onResource(k)}
              onClick={() => onResource(k)}
              className={cn(
                "rounded-lg px-3 py-1 text-xs transition",
                resourceKey === k
                  ? "bg-[#00bbff] text-black font-medium"
                  : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700",
              )}
              title={resourceVariants[k].name}
            >
              {k}
            </button>
          ))}
        </div>
        <div className="mt-1.5 text-[11px] text-zinc-500 px-1">
          <span className="text-zinc-300">
            {productVariants[productKey].name}
          </span>{" "}
          · {productVariants[productKey].blurb}
          <span className="mx-2 text-zinc-700">|</span>
          <span className="text-zinc-300">
            {resourceVariants[resourceKey].name}
          </span>{" "}
          · {resourceVariants[resourceKey].blurb}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Fake landing — minimal, just enough context                                 */
/* ────────────────────────────────────────────────────────────────────────── */

function FakeLanding() {
  return (
    <div className="relative">
      <div className="absolute inset-0 -z-10">
        <Image
          src={wp.mesh}
          alt=""
          fill
          priority
          sizes="100vw"
          className="object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#111111]/60 to-[#111111]" />
      </div>

      <section className="pt-44 pb-32 px-6">
        <div className="mx-auto max-w-4xl text-center">
          <div className="inline-flex items-center gap-2 rounded-full bg-zinc-900/60 backdrop-blur-xl px-3 py-1 text-xs text-zinc-300">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            Now in private beta
          </div>
          <h1 className="mt-6 text-6xl font-medium tracking-tight leading-[1.05]">
            The AI assistant that
            <br />
            <span className="text-zinc-400">actually does the work.</span>
          </h1>
          <p className="mt-6 text-lg text-zinc-400 max-w-xl mx-auto">
            Voice, workflows, memory, and 50+ tools — across every channel.
          </p>
          <div className="mt-8 flex items-center justify-center gap-3">
            <button
              type="button"
              className="rounded-xl bg-[#00bbff] px-5 h-11 text-sm font-medium text-black"
            >
              Start free
            </button>
            <button
              type="button"
              className="rounded-xl bg-zinc-900/60 backdrop-blur-xl px-5 h-11 text-sm text-zinc-200"
            >
              Watch demo
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
