"use client";

import { Chip } from "@heroui/chip";
import Image from "next/image";
import { notFound } from "next/navigation";
import { useReducer, useRef, useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { WelcomeChat } from "@/features/chat/components/welcome/WelcomeChat";
import { CompletedStageAccordion } from "@/features/onboarding/components/CompletedStageAccordion";
import { CompletedStagesTimeline } from "@/features/onboarding/components/CompletedStagesTimeline";
import { ComposerCTA } from "@/features/onboarding/components/ComposerCTA";
import { OnboardingCTAButton } from "@/features/onboarding/components/OnboardingCTAButton";
import { OnboardingInput } from "@/features/onboarding/components/OnboardingInput";
import { OnboardingIntro } from "@/features/onboarding/components/OnboardingIntro";
import { OnboardingMessages } from "@/features/onboarding/components/OnboardingMessages";
import { OnboardingPlatformConnect } from "@/features/onboarding/components/OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "@/features/onboarding/components/OnboardingPlatformPreview";
import { OnboardingProcessing } from "@/features/onboarding/components/OnboardingProcessing";
import { OnboardingProgress } from "@/features/onboarding/components/OnboardingProgress";
import { OnboardingTodoCards } from "@/features/onboarding/components/OnboardingTodoCards";
import { OnboardingWorkflowCards } from "@/features/onboarding/components/OnboardingWorkflowCards";
import { RevealIntroBubble } from "@/features/onboarding/components/RevealIntroBubble";
import { TodosRevealCard } from "@/features/onboarding/components/reveal/TodosRevealCard";
import { WorkflowsRevealCard } from "@/features/onboarding/components/reveal/WorkflowsRevealCard";
import { WritingStyleRevealCard } from "@/features/onboarding/components/reveal/WritingStyleRevealCard";
import { ClarifyComposer } from "@/features/onboarding/components/stages/Clarify";
import { Platforms } from "@/features/onboarding/components/stages/Platforms";
import { SelectedTodoIndicator } from "@/features/onboarding/components/stages/RevealTodos";
import {
  RevealWritingStyle,
  RevealWritingStyleComposer,
} from "@/features/onboarding/components/stages/RevealWritingStyle";
import { Workflows } from "@/features/onboarding/components/stages/Workflows";
import { professionOptions } from "@/features/onboarding/constants";
import { BOT_BUBBLE_DEFAULTS } from "@/features/onboarding/constants/bubbleDefaults";
import { CLARIFY_MOCK_QUESTIONS } from "@/features/onboarding/constants/clarify";
import {
  REVEAL_TODOS_INTRO_GMAIL,
  REVEAL_TODOS_INTRO_NO_GMAIL,
  REVEAL_WRITING_STYLE_INTRO,
} from "@/features/onboarding/constants/messages";
import {
  PLATFORM_ICONS,
  PLATFORM_LABELS,
  PLATFORM_PREVIEW_ORDER,
  type PlatformPreviewPlatform,
} from "@/features/onboarding/constants/platformPreviewMessages";
import type { UseOnboardingChatReturn } from "@/features/onboarding/hooks/useOnboardingChat";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";
import type { OnboardingState } from "@/features/onboarding/state/types";
import type {
  OnboardingStage,
  PersonalizationData,
} from "@/features/onboarding/types/websocket";
import { countAnsweredClarify } from "@/features/onboarding/utils/clarifyHelpers";
import { useUserStore } from "@/stores/userStore";

if (process.env.NODE_ENV === "production") {
  notFound();
}

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

const DUMMY_CHAT: UseOnboardingChatReturn = {
  streamMessages: [],
  chatInputValue: "",
  isChatSending: false,
  isTodoExecutionDone: true,
  setChatInputValue: () => {},
  sendChatMessage: async () => {},
};

const DUMMY_PERSONALIZATION: PersonalizationData = {
  phase: "personalization_complete",
  bio_status: "completed",
  has_personalization: true,
  name: "Aryan",
  writing_style: {
    style_summary: DUMMY_WRITING_STYLE.style_summary,
    example: DUMMY_WRITING_STYLE.example,
  },
  onboarding_todos: DUMMY_TODOS.map((t) => ({
    id: t.id,
    title: t.title,
    description: t.description ?? null,
    source_email: t.source_email ?? null,
  })),
  suggested_workflows: DUMMY_WORKFLOWS.map((w) => ({
    id: w.id,
    title: w.title,
    description: w.description ?? "",
    steps: (w.categories ?? []).map((category) => ({ category })),
  })),
};

const GMAIL_STAGES: OnboardingStage[] = [
  "inbox_scanning",
  "writing_style_ready",
  "triage_ready",
  "todos_ready",
  "workflows_ready",
];

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
        />
      </div>
    </DemoSection>
  );
}

const MESSAGE_BREAK_SAMPLES = [
  "Hey! I'm GAIA.<NEW_MESSAGE_BREAK>What should I call you?",
  "Nice to meet you, Aryan!<NEW_MESSAGE_BREAK>What do you do?<NEW_MESSAGE_BREAK>I'll use this to tailor your setup.",
  "Got it.<NEW_MESSAGE_BREAK>Mind if I peek at your inbox?<NEW_MESSAGE_BREAK>I'll draft todos from anything urgent.<NEW_MESSAGE_BREAK>You can disconnect any time.",
];

function MessageBreakStaggerDemo() {
  const [nonce, setNonce] = useState(0);
  const [activeIdx, setActiveIdx] = useState(0);
  const sample = MESSAGE_BREAK_SAMPLES[activeIdx];

  return (
    <DemoSection label="NEW_MESSAGE_BREAK stagger">
      <p className="text-xs text-zinc-500">
        Each segment between <code>&lt;NEW_MESSAGE_BREAK&gt;</code> tokens fades
        in with a 0.35s stagger. Single-segment messages skip the animation.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {MESSAGE_BREAK_SAMPLES.map((_, i) => (
          <Chip
            // biome-ignore lint/suspicious/noArrayIndexKey: stable list
            key={i}
            variant={activeIdx === i ? "solid" : "flat"}
            color={activeIdx === i ? "primary" : "default"}
            size="sm"
            onClick={() => {
              setActiveIdx(i);
              setNonce((n) => n + 1);
            }}
            className="cursor-pointer select-none"
          >
            {MESSAGE_BREAK_SAMPLES[i].split("<NEW_MESSAGE_BREAK>").length}{" "}
            bubbles
          </Chip>
        ))}
        <button
          type="button"
          onClick={() => setNonce((n) => n + 1)}
          className="cursor-pointer rounded-lg bg-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-600"
        >
          Replay
        </button>
      </div>
      <div key={`${activeIdx}-${nonce}`} className="pt-2">
        <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={sample} />
      </div>
    </DemoSection>
  );
}

function ClarifyDemo() {
  const [state, dispatch] = useReducer(reducer, initialState, (s) => ({
    ...s,
    clarifyQuestions: CLARIFY_MOCK_QUESTIONS,
    clarifyActiveTab: CLARIFY_MOCK_QUESTIONS[0]?.id ?? null,
  }));

  const handleReset = () => {
    dispatch({ type: "reset" });
    dispatch({ type: "clarifyLoaded", questions: CLARIFY_MOCK_QUESTIONS });
  };

  return (
    <DemoSection label="ClarifyComposer (no-Gmail follow-up)">
      <div className="flex flex-col gap-3">
        <div className="mx-auto w-full max-w-xl">
          <ClarifyComposer state={state} dispatch={dispatch} />
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleReset}
            className="cursor-pointer rounded-lg bg-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-700"
          >
            Reset
          </button>
          <span className="text-xs text-zinc-500">
            {state.clarifySubmitted
              ? "Submitted — answers locked"
              : `${countAnsweredClarify(state)}/${state.clarifyQuestions?.length ?? 0} answered`}
          </span>
        </div>
      </div>
    </DemoSection>
  );
}

// Wrapping the fixed-position bar in a `transform` parent scopes it to the demo card instead of the viewport.
function ProgressDemo() {
  const [step, setStep] = useState(2);
  const total = 7;
  return (
    <DemoSection label="OnboardingProgress (top bar + restart)">
      <div
        className="relative h-20 overflow-hidden rounded-2xl border border-zinc-800 bg-primary-bg"
        style={{ transform: "translateZ(0)" }}
      >
        <OnboardingProgress
          currentStep={step}
          totalSteps={total}
          onRestart={() => setStep(0)}
        />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          className="cursor-pointer rounded-lg bg-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-700"
        >
          ← Step
        </button>
        <span className="text-xs text-zinc-500">
          {step} / {total}
        </span>
        <button
          type="button"
          onClick={() => setStep((s) => Math.min(total, s + 1))}
          className="cursor-pointer rounded-lg bg-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-600"
        >
          Step →
        </button>
      </div>
    </DemoSection>
  );
}

function IntroDemo() {
  const [playing, setPlaying] = useState(false);
  return (
    <DemoSection label="OnboardingIntro (fullscreen intro)">
      <p className="text-xs text-zinc-500">
        The intro mounts a fixed-position overlay with audio. Click play to
        watch the full sequence; it calls <code>onComplete</code> when done.
      </p>
      <button
        type="button"
        onClick={() => setPlaying(true)}
        className="w-fit cursor-pointer rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-black hover:bg-primary/90"
      >
        Play intro
      </button>
      {playing && <OnboardingIntro onComplete={() => setPlaying(false)} />}
    </DemoSection>
  );
}

function CTAComposerDemo() {
  return (
    <DemoSection label="ComposerCTA + OnboardingCTAButton">
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-primary-bg/40">
        <ComposerCTA>
          <OnboardingCTAButton onClick={() => {}}>
            Looks good
          </OnboardingCTAButton>
        </ComposerCTA>
      </div>
      <div className="flex flex-wrap gap-2">
        <OnboardingCTAButton onClick={() => {}}>Understood</OnboardingCTAButton>
        <OnboardingCTAButton href="/onboarding/demo">
          Continue to GAIA
        </OnboardingCTAButton>
        <OnboardingCTAButton onClick={() => {}} hideEndIcon>
          No icon
        </OnboardingCTAButton>
      </div>
    </DemoSection>
  );
}

function OnboardingInputDemo() {
  const qaRef = useRef<HTMLInputElement>(null);
  const focusRef = useRef<HTMLInputElement>(null);
  const freeChatRef = useRef<HTMLInputElement>(null);
  const [qaDraft, setQaDraft] = useState("");
  const [qaProfession, setQaProfession] = useState<string | null>(null);
  const [focusDraft, setFocusDraft] = useState("");
  const [freeChatValue, setFreeChatValue] = useState("");
  const [questionIndex, setQuestionIndex] = useState(0);

  return (
    <DemoSection label="OnboardingInput (qa / focus / freeChat)">
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-500">QA question index:</span>
        {[0, 1, 2, 3].map((i) => (
          <Chip
            key={i}
            variant={questionIndex === i ? "solid" : "flat"}
            color={questionIndex === i ? "primary" : "default"}
            size="sm"
            onClick={() => setQuestionIndex(i)}
            className="cursor-pointer select-none"
          >
            Q{i + 1}
          </Chip>
        ))}
      </div>

      <p className="text-[10px] uppercase tracking-widest text-zinc-600">
        mode = qa
      </p>
      <OnboardingInput
        mode="qa"
        questionIndex={questionIndex}
        draftText={qaDraft}
        draftProfession={qaProfession}
        inputRef={qaRef}
        onSubmit={(e) => e.preventDefault()}
        onInputChange={setQaDraft}
        onProfessionSelect={(key) =>
          setQaProfession(key != null ? String(key) : null)
        }
        onProfessionInputChange={(value) => setQaProfession(value || null)}
        onGmailSkip={() => {}}
      />

      <p className="mt-4 text-[10px] uppercase tracking-widest text-zinc-600">
        mode = focus
      </p>
      <OnboardingInput
        mode="focus"
        draftText={focusDraft}
        inputRef={focusRef}
        onSubmit={(e) => e.preventDefault()}
        onInputChange={setFocusDraft}
      />

      <p className="mt-4 text-[10px] uppercase tracking-widest text-zinc-600">
        mode = freeChat
      </p>
      <OnboardingInput
        mode="freeChat"
        inputRef={freeChatRef}
        freeChatValue={freeChatValue}
        isSending={false}
        onFreeChatChange={setFreeChatValue}
        onFreeChatSubmit={(e) => e.preventDefault()}
      />
    </DemoSection>
  );
}

const SAMPLE_MESSAGES = [
  {
    id: "m1",
    type: "bot" as const,
    content: "Hey! I'm GAIA. What should I call you?",
  },
  { id: "m2", type: "user" as const, content: "Aryan" },
  {
    id: "m3",
    type: "bot" as const,
    content: "Nice to meet you, Aryan!<NEW_MESSAGE_BREAK>What do you do?",
  },
  { id: "m4", type: "user" as const, content: "Founder, building GAIA." },
  {
    id: "m5",
    type: "bot" as const,
    content: "Got it. Mind if I peek at your inbox?",
  },
];

function OnboardingMessagesDemo() {
  const [showChecklist, setShowChecklist] = useState(false);
  return (
    <DemoSection label="OnboardingMessages (transcript renderer)">
      <div className="flex items-center gap-2">
        <Chip
          variant={showChecklist ? "solid" : "flat"}
          color={showChecklist ? "primary" : "default"}
          size="sm"
          onClick={() => setShowChecklist((v) => !v)}
          className="cursor-pointer select-none"
        >
          {showChecklist ? "Hide" : "Show"} processing checklist
        </Chip>
      </div>
      <div className="rounded-2xl border border-zinc-800 bg-primary-bg/40 p-4">
        <OnboardingMessages
          messages={SAMPLE_MESSAGES}
          processingChecklist={
            showChecklist ? (
              <OnboardingProcessing
                hasGmail
                progressByStage={{
                  inbox_scanning: "Fetched 312 emails",
                }}
                completedStages={new Set()}
              />
            ) : null
          }
        />
      </div>
    </DemoSection>
  );
}

function CompletedStagesTimelineDemo() {
  const [acked, setAcked] = useState({
    writing: true,
    todos: true,
    workflows: true,
    platforms: false,
  });

  const state: OnboardingState = {
    ...initialState,
    server: DUMMY_PERSONALIZATION,
    responses: { profession: "Founder" },
    ackedWritingStyle: acked.writing,
    ackedTodos: acked.todos,
    workflowsConfirmed: acked.workflows,
    platformsConfirmed: acked.platforms,
    connectedPlatform: acked.platforms ? "telegram" : null,
  };

  const toggle = (k: keyof typeof acked) =>
    setAcked((a) => ({ ...a, [k]: !a[k] }));

  return (
    <DemoSection label="CompletedStagesTimeline (accordion stack)">
      <div className="flex flex-wrap items-center gap-2">
        {(Object.keys(acked) as (keyof typeof acked)[]).map((k) => (
          <Chip
            key={k}
            variant={acked[k] ? "solid" : "flat"}
            color={acked[k] ? "success" : "default"}
            size="sm"
            onClick={() => toggle(k)}
            className="cursor-pointer select-none"
          >
            {k}
          </Chip>
        ))}
      </div>
      <CompletedStagesTimeline
        state={state}
        dispatch={() => {}}
        chat={DUMMY_CHAT}
      />
    </DemoSection>
  );
}

function RevealWritingStyleStageDemo() {
  const [acked, setAcked] = useState(false);
  const state: OnboardingState = {
    ...initialState,
    server: DUMMY_PERSONALIZATION,
    responses: { profession: "Founder" },
    ackedWritingStyle: acked,
    progressByStage: acked
      ? { triage_analyzing: "Found 8 important threads" }
      : {},
  };
  return (
    <DemoSection label="RevealWritingStyle stage (pre/post ack)">
      <div className="flex items-center gap-2">
        <Chip
          variant={acked ? "solid" : "flat"}
          color={acked ? "success" : "default"}
          size="sm"
          onClick={() => setAcked((v) => !v)}
          className="cursor-pointer select-none"
        >
          {acked ? "Acked" : "Pre-ack"}
        </Chip>
      </div>
      <RevealWritingStyle state={state} />
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-primary-bg/40">
        <RevealWritingStyleComposer state={state} dispatch={() => {}} />
      </div>
    </DemoSection>
  );
}

function WorkflowsStageDemo() {
  const state: OnboardingState = {
    ...initialState,
    server: DUMMY_PERSONALIZATION,
    workflowsConfirmed: false,
  };
  return (
    <DemoSection label="Workflows stage (intro bubble + cards)">
      <Workflows state={state} dispatch={() => {}} />
    </DemoSection>
  );
}

function PlatformsStageDemo() {
  const state: OnboardingState = {
    ...initialState,
    server: DUMMY_PERSONALIZATION,
    responses: { profession: "Founder" },
  };
  return (
    <DemoSection label="Platforms stage (preview + connect)">
      <Platforms state={state} dispatch={() => {}} />
    </DemoSection>
  );
}

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

        <ProgressDemo />
        <IntroDemo />

        <CTAComposerDemo />
        <OnboardingInputDemo />

        <OnboardingMessagesDemo />

        <MessageBreakStaggerDemo />

        <ProcessingDemo />

        <ClarifyDemo />

        <DemoSection label="RevealIntroBubble">
          <RevealIntroBubble text={REVEAL_WRITING_STYLE_INTRO} />
          <RevealIntroBubble text={REVEAL_TODOS_INTRO_GMAIL} />
          <RevealIntroBubble text={REVEAL_TODOS_INTRO_NO_GMAIL} />
        </DemoSection>

        <DemoSection label="WritingStyleRevealCard">
          <WritingStyleRevealCard
            style_summary={DUMMY_WRITING_STYLE.style_summary}
            example={DUMMY_WRITING_STYLE.example}
            profession={DUMMY_WRITING_STYLE.profession}
          />
        </DemoSection>

        <RevealWritingStyleStageDemo />

        <DemoSection label="TodosRevealCard (collapsed summary)">
          <TodosRevealCard
            todos={DUMMY_TODOS.map((t) => ({
              id: t.id,
              title: t.title,
              source_email: t.source_email,
            }))}
          />
        </DemoSection>
        <DemoSection label="WorkflowsRevealCard (collapsed summary)">
          <WorkflowsRevealCard workflows={DUMMY_WORKFLOWS} />
        </DemoSection>

        <TodoCardsDemo />

        <DemoSection label="OnboardingWorkflowCards">
          <OnboardingWorkflowCards workflows={DUMMY_WORKFLOWS} />
        </DemoSection>

        <WorkflowsStageDemo />

        <PlatformConnectDemo />

        <PlatformsStageDemo />

        <DemoSection label="WelcomeChat (post-onboarding /c)">
          <div className="rounded-2xl border border-zinc-800 bg-primary-bg p-4">
            <WelcomeChat surface="onboarding" />
          </div>
        </DemoSection>

        <DemoSection label="SelectedTodoIndicator">
          <div className="space-y-3">
            <SelectedTodoIndicator
              title={DUMMY_TODOS[0].title}
              sourceEmail={DUMMY_TODOS[0].source_email ?? null}
            />
            <SelectedTodoIndicator
              title={DUMMY_TODOS[1].title}
              sourceEmail={null}
            />
          </div>
        </DemoSection>

        <DemoSection label="Run-now demo panel (RevealTodos stream mode)">
          <div className="ml-10.75 space-y-4 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl">
            <SelectedTodoIndicator
              title={DUMMY_TODOS[0].title}
              sourceEmail={DUMMY_TODOS[0].source_email ?? null}
            />
            <ChatBubbleBot
              {...BOT_BUBBLE_DEFAULTS}
              text="Got it — pulled the latest Crunchbase data plus your inbox threads. Top fits: Sequoia (Sonya Huang), Index (Mike Volpi), Greylock (Saam Motamedi), Conviction (Sarah Guo), Lightspeed (Guru Chahal). Drafted a short memo for each in your notes."
              message_id="demo-run-now"
              loading={false}
              date={new Date().toISOString()}
              hideAvatar
            />
          </div>
        </DemoSection>

        <DemoSection label="CompletedStageAccordion">
          <div className="space-y-3">
            <CompletedStageAccordion
              itemKey="short"
              title="Writing style saved"
            >
              <p className="text-sm text-zinc-400">
                Stage payload renders here when expanded.
              </p>
            </CompletedStageAccordion>
            <CompletedStageAccordion
              itemKey="long"
              title={`Ran "Break down a 48-hour sales pipeline sprint into tasks"`}
            >
              <p className="text-sm text-zinc-400">
                Title now truncates with an ellipsis; the chevron stays inside
                the pill.
              </p>
            </CompletedStageAccordion>
            <CompletedStageAccordion itemKey="medium" title="3 workflows added">
              <OnboardingWorkflowCards workflows={DUMMY_WORKFLOWS} embedded />
            </CompletedStageAccordion>
          </div>
        </DemoSection>

        <CompletedStagesTimelineDemo />
      </div>
    </div>
  );
}
