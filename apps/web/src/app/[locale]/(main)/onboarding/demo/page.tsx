"use client";

import { Chip } from "@heroui/chip";
import Image from "next/image";
import { notFound } from "next/navigation";
import { useState } from "react";
import { HoloCard } from "@/components/ui/holo-card/HoloCard";
import { WelcomeChat } from "@/features/chat/components/welcome/WelcomeChat";
import { OnboardingPlatformConnect } from "@/features/onboarding/components/OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "@/features/onboarding/components/OnboardingPlatformPreview";
import { OnboardingProcessing } from "@/features/onboarding/components/OnboardingProcessing";
import { OnboardingTodoCards } from "@/features/onboarding/components/OnboardingTodoCards";
import { OnboardingWorkflowCards } from "@/features/onboarding/components/OnboardingWorkflowCards";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import { WritingStyleRevealCard } from "@/features/onboarding/components/reveal/WritingStyleRevealCard";
import { professionOptions } from "@/features/onboarding/constants";
import {
  PLATFORM_ICONS,
  PLATFORM_LABELS,
  PLATFORM_PREVIEW_ORDER,
  type PlatformPreviewPlatform,
} from "@/features/onboarding/constants/platformPreviewMessages";
import type { OnboardingStage } from "@/features/onboarding/types/websocket";
import { useUserStore } from "@/stores/userStore";

if (process.env.NODE_ENV === "production") {
  notFound();
}

// ── Dummy data ────────────────────────────────────────────────────────────────

const DUMMY_WRITING_STYLE = {
  style_summary:
    "Opens with 'Hey' or 'Hi [name]', rarely uses formal salutations. Keeps sentences short and punchy, rarely more than 2 clauses. Signs off with 'Cheers' or just their name. Uses lowercase occasionally in casual threads and drops trailing periods on short replies.",
  example: {
    greeting: "Hey Sarah,",
    body: [
      "Just saw your message, totally agree on pushing the deadline. Let me loop in the design team and get back to you by EOD.",
    ],
    signoff: "Cheers,",
    name: "Aryan",
  },
  profession: "Founder",
};

const DUMMY_TODOS = [
  {
    id: "1",
    title: "Research top 5 VCs active in AI infra and summarize thesis fit",
    source_email: {
      sender: "Michael Seibel <ms@ycombinator.com>",
      subject: "Re: GAIA — office hours",
    },
  },
  {
    id: "2",
    title: "Draft cold outreach for warm investor introductions",
    description: "Based on your current raise and existing network overlap",
  },
  {
    id: "3",
    title: "Break down Series A fundraising timeline into weekly milestones",
    source_email: {
      sender: "Stripe Atlas <atlas@stripe.com>",
      subject: "Your incorporation docs are ready",
    },
  },
];

const DUMMY_WORKFLOWS = [
  {
    id: "1",
    title: "Flag investor emails and draft follow-ups",
    description:
      "Detects emails from known investors or VC domains, drafts a personalized follow-up, and adds it to your review queue.",
    categories: ["gmail", "googlecalendar"],
  },
  {
    id: "2",
    title: "Summarize new bug reports with steps to reproduce",
    description:
      "Monitors GitHub and Linear for new bug reports, cross-references with your codebase, and creates a summary with reproduction steps.",
    categories: ["github", "linear"],
  },
  {
    id: "3",
    title: "Daily standup digest from Slack threads",
    description:
      "Every morning, summarizes unread Slack threads and open Linear issues into a concise standup brief.",
    categories: ["slack", "linear", "notifications"],
  },
];

const DUMMY_HOLO_CARD = {
  house: "bluehaven" as const,
  name: "Aryan",
  personality_phrase: "Midnight Architect",
  user_bio:
    "Aryan ships code like it owes him money — fast, opinionated, and somehow always elegant. The type to redesign an entire onboarding flow at 2am because something felt 3px off. Unreasonable ambition, very reasonable commit messages.",
  account_number: 1247,
  member_since: "April 2025",
  overlay_color: "rgba(59, 130, 246, 0.15)",
  overlay_opacity: 40,
  holo_card_id: "demo-card-id",
};

// ── Processing simulation ─────────────────────────────────────────────────────

const GMAIL_STAGES: OnboardingStage[] = [
  "inbox_scanning",
  "writing_style_ready",
  "triage_ready",
  "todos_ready",
  "workflows_ready",
];

// Live progress text emitted by each *_creating/*_progress stage. The
// completion stage that flips its step ✓ also clears the matching slot —
// mirroring the reducer's PROGRESS_CLEARED_BY logic so the demo behaves
// identically to production.
const PROGRESS_BY_COMPLETION: Partial<
  Record<OnboardingStage, { stage: OnboardingStage; text: string }>
> = {
  inbox_scanning: { stage: "inbox_scanning", text: "Fetched 312 emails" },
  writing_style_ready: {
    stage: "writing_style_progress",
    text: "Analyzing tone and phrasing",
  },
  triage_ready: {
    stage: "triage_analyzing",
    text: "Found 8 important threads",
  },
  todos_ready: {
    stage: "todos_creating",
    text: "Drafting todos from your inbox",
  },
  workflows_ready: {
    stage: "workflows_creating",
    text: "Drafting workflow ideas",
  },
};

function initialProgress(): Partial<Record<OnboardingStage, string>> {
  const first = PROGRESS_BY_COMPLETION[GMAIL_STAGES[0]];
  return first ? { [first.stage]: first.text } : {};
}

function ProcessingDemo() {
  const [completedStages, setCompletedStages] = useState<Set<OnboardingStage>>(
    new Set(),
  );
  const [progressByStage, setProgressByStage] =
    useState<Partial<Record<OnboardingStage, string>>>(initialProgress);

  const advance = () => {
    const nextIdx = completedStages.size;
    if (nextIdx >= GMAIL_STAGES.length) return;
    const next = GMAIL_STAGES[nextIdx];
    if (!next) return;
    setCompletedStages((prev) => new Set([...prev, next]));
    setProgressByStage((prev) => {
      const cleared = { ...prev };
      const completing = PROGRESS_BY_COMPLETION[next];
      if (completing) delete cleared[completing.stage];
      const following = GMAIL_STAGES[nextIdx + 1];
      const seed = following && PROGRESS_BY_COMPLETION[following];
      if (seed) cleared[seed.stage] = seed.text;
      return cleared;
    });
  };

  const reset = () => {
    setCompletedStages(new Set());
    setProgressByStage(initialProgress());
  };

  return (
    <DemoSection label="OnboardingProcessing">
      <div className="flex flex-col gap-4">
        <OnboardingProcessing
          hasGmail
          progressByStage={progressByStage}
          completedStages={completedStages}
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={advance}
            disabled={completedStages.size === GMAIL_STAGES.length}
            className="cursor-pointer rounded-lg bg-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-600 disabled:opacity-40"
          >
            Complete next stage →
          </button>
          <button
            type="button"
            onClick={reset}
            className="cursor-pointer rounded-lg bg-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-700"
          >
            Reset
          </button>
        </div>
      </div>
    </DemoSection>
  );
}

// ── Todo cards simulation ─────────────────────────────────────────────────────

function TodoCardsDemo() {
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());

  const handleExecute = (id: string) => {
    setExecutingId(id);
    setTimeout(() => {
      setCompletedIds((prev) => new Set([...prev, id]));
      setExecutingId(null);
    }, 1800);
  };

  return (
    <DemoSection label="OnboardingTodoCards">
      <OnboardingTodoCards
        todos={DUMMY_TODOS}
        onExecuteTodo={handleExecute}
        isExecuting={executingId !== null}
        executingTodoId={executingId}
        completedTodoIds={completedIds}
      />
    </DemoSection>
  );
}

// ── Platform connect simulation ───────────────────────────────────────────────

function PlatformConnectDemo() {
  const [connected, setConnected] = useState<string | null>(null);
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);
  const [pinnedPlatform, setPinnedPlatform] =
    useState<PlatformPreviewPlatform | null>(null);
  const [profession, setProfession] = useState<string>("entrepreneur");

  const storeName = useUserStore((s) => s.name);
  const storeAvatar = useUserStore((s) => s.profilePicture);

  const effectivePlatform = hoveredPlatform ?? pinnedPlatform;

  return (
    <DemoSection label="OnboardingPlatformConnect">
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500">Platform:</span>
          {PLATFORM_PREVIEW_ORDER.map((p) => {
            const isActive = pinnedPlatform === p;
            return (
              <Chip
                key={p}
                variant={isActive ? "solid" : "flat"}
                color={isActive ? "primary" : "default"}
                size="sm"
                onClick={() =>
                  setPinnedPlatform((current) => (current === p ? null : p))
                }
                className="cursor-pointer select-none"
                startContent={
                  <Image
                    src={PLATFORM_ICONS[p]}
                    alt=""
                    width={16}
                    height={16}
                    className="h-4 w-4 shrink-0 rounded-[3px]"
                    aria-hidden
                  />
                }
              >
                {PLATFORM_LABELS[p]}
              </Chip>
            );
          })}
          {pinnedPlatform && (
            <button
              type="button"
              className="text-xs text-zinc-500 underline-offset-2 hover:underline"
              onClick={() => setPinnedPlatform(null)}
            >
              clear
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500">Profession:</span>
          {professionOptions.slice(0, 10).map((p) => {
            const isActive = profession === p.value;
            return (
              <Chip
                key={p.value}
                variant={isActive ? "solid" : "flat"}
                color={isActive ? "primary" : "default"}
                size="sm"
                onClick={() => setProfession(p.value)}
                className="cursor-pointer select-none"
              >
                {p.label}
              </Chip>
            );
          })}
        </div>
      </div>
      {!connected && (
        <OnboardingPlatformPreview
          profession={profession}
          hoveredPlatform={effectivePlatform}
          userName={storeName}
          userAvatar={storeAvatar}
        />
      )}
      <div className="mt-1">
        <OnboardingPlatformConnect
          onConnect={(p) => setConnected(p)}
          onSkip={() => setConnected(null)}
          onHoverPlatform={setHoveredPlatform}
          connectedPlatform={connected}
        />
      </div>
    </DemoSection>
  );
}

// ── Layout helpers ────────────────────────────────────────────────────────────

function DemoSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <p className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
        {label}
      </p>
      {children}
      <div className="mt-2 border-t border-zinc-800" />
    </section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OnboardingDemoPage() {
  return (
    <div className="h-full overflow-y-auto bg-primary-bg px-6 py-16">
      <div className="mx-auto max-w-2xl space-y-10">
        <div className="mb-10">
          <p className="text-xs font-mono uppercase tracking-widest text-zinc-600">
            Design sandbox
          </p>
          <h1 className="mt-1 text-xl font-medium text-zinc-200">
            Onboarding Components
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            All components with simulated dummy data. Not wired to backend.
          </p>
        </div>

        {/* Processing widget */}
        <ProcessingDemo />

        {/* Writing style */}
        <DemoSection label="WritingStyleRevealCard">
          <WritingStyleRevealCard
            style_summary={DUMMY_WRITING_STYLE.style_summary}
            example={DUMMY_WRITING_STYLE.example}
            profession={DUMMY_WRITING_STYLE.profession}
          />
        </DemoSection>

        {/* Todos */}
        <TodoCardsDemo />

        {/* Workflows */}
        <DemoSection label="OnboardingWorkflowCards">
          <OnboardingWorkflowCards workflows={DUMMY_WORKFLOWS} />
        </DemoSection>

        {/* Platform connect */}
        <PlatformConnectDemo />

        {/* Welcome chat (post-onboarding /c first visit) */}
        <DemoSection label="WelcomeChat (post-onboarding /c)">
          <div className="rounded-2xl border border-zinc-800 bg-primary-bg p-4">
            <WelcomeChat surface="onboarding" />
          </div>
        </DemoSection>

        {/* Holo card — now baked with stamp die-cut */}
        <DemoSection label="HoloCardReveal">
          <HoloCardReveal personalizationData={DUMMY_HOLO_CARD} />
        </DemoSection>
      </div>
    </div>
  );
}
