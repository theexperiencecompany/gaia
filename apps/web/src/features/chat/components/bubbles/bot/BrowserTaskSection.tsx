"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Spinner } from "@heroui/spinner";
import {
  Alert01Icon,
  CheckmarkCircle02Icon,
  CreditCardIcon,
  CursorInWindowIcon,
  EyeIcon,
  GlobeIcon,
  ShieldUserIcon,
  SquareArrowUpRight02Icon,
  StopCircleIcon,
} from "@icons";
import Image from "next/image";
import { useMemo, useState } from "react";
import { useImageDialog } from "@/stores/uiStore";
import type {
  BrowserHandoffSnapshot,
  BrowserResultSnapshot,
  BrowserSensitiveCategory,
  BrowserSessionSnapshot,
  BrowserSessionStatus,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "@/types/features/browserTaskTypes";
import { browserApi } from "../../../api/browserApi";

interface BrowserTaskSectionProps {
  data: BrowserTaskSnapshot | BrowserTaskSnapshot[];
}

interface FoldedState {
  session?: BrowserSessionSnapshot;
  steps: BrowserStepSnapshot[];
  handoffs: BrowserHandoffSnapshot[];
  result?: BrowserResultSnapshot;
}

type UiStatus = BrowserSessionStatus | "paused";

// Machine states → plain language the user understands at a glance.
const STATUS_META: Record<
  UiStatus,
  {
    label: string;
    color: "default" | "primary" | "success" | "danger" | "warning";
  }
> = {
  starting: { label: "Starting", color: "default" },
  running: { label: "Working", color: "primary" },
  paused: { label: "Needs you", color: "warning" },
  completed: { label: "Done", color: "success" },
  failed: { label: "Couldn't finish", color: "danger" },
  cancelled: { label: "Stopped", color: "default" },
};

// Each sensitive category gets an icon + a title that says what the user does.
const HANDOFF_META: Record<
  BrowserSensitiveCategory,
  { icon: React.ComponentType<{ className?: string }>; title: string }
> = {
  none: { icon: CursorInWindowIcon, title: "Take over for a moment" },
  payment: { icon: CreditCardIcon, title: "Finish the payment yourself" },
  credentials: { icon: ShieldUserIcon, title: "Sign in to continue" },
  irreversible: { icon: Alert01Icon, title: "Confirm this step to continue" },
};

function fold(snapshots: BrowserTaskSnapshot[]): FoldedState {
  let session: BrowserSessionSnapshot | undefined;
  let result: BrowserResultSnapshot | undefined;
  const steps = new Map<number, BrowserStepSnapshot>();
  const handoffs = new Map<string, BrowserHandoffSnapshot>();

  for (const snap of snapshots) {
    if (snap.kind === "session") session = snap;
    else if (snap.kind === "step") steps.set(snap.index, snap);
    else if (snap.kind === "handoff")
      handoffs.set(snap.handoff_id, snap); // last wins
    else if (snap.kind === "result") result = snap;
  }

  return {
    session,
    result,
    steps: [...steps.values()].sort((a, b) => a.index - b.index),
    handoffs: [...handoffs.values()],
  };
}

function StepRow({ step }: { step: BrowserStepSnapshot }) {
  const { openDialog } = useImageDialog();
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-medium text-zinc-400">
          {step.index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug text-zinc-100">
            {step.goal}
          </p>
          {step.url && (
            <p className="mt-0.5 truncate text-xs text-zinc-500">{step.url}</p>
          )}
        </div>
      </div>
      {step.screenshot && (
        <button
          type="button"
          onClick={() => openDialog(step.screenshot as string)}
          className="group mt-2.5 block w-full overflow-hidden rounded-xl ring-1 ring-white/5 transition hover:ring-white/20"
          aria-label={`Enlarge step ${step.index} screenshot`}
        >
          <Image
            src={step.screenshot}
            alt={`Step ${step.index} screenshot`}
            width={1280}
            height={720}
            className="h-auto w-full transition group-hover:opacity-90"
            unoptimized
          />
        </button>
      )}
    </div>
  );
}

function HandoffPrompt({ handoff }: { handoff: BrowserHandoffSnapshot }) {
  const [decided, setDecided] = useState<"continue" | "cancel" | null>(null);
  const [pending, setPending] = useState(false);
  const meta = HANDOFF_META[handoff.category] ?? HANDOFF_META.none;
  const Icon = meta.icon;

  const decide = async (decision: "continue" | "cancel") => {
    setPending(true);
    setDecided(decision);
    try {
      await browserApi.postHandoffDecision(handoff.handoff_id, decision);
    } catch {
      setDecided(null);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="rounded-2xl bg-amber-950/30 p-3.5 ring-1 ring-amber-500/25">
      <div className="flex items-start gap-2.5">
        <span className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
          <Icon className="size-4 text-amber-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-amber-100">{meta.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-amber-200/70">
            {handoff.reason}
          </p>
        </div>
      </div>

      {handoff.live_view_url && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center gap-1.5 px-0.5">
            <CursorInWindowIcon className="size-3.5 text-amber-300/80" />
            <span className="text-[11px] font-medium text-amber-200/80">
              Live browser — you're in control
            </span>
          </div>
          <div className="overflow-hidden rounded-xl ring-1 ring-amber-500/20">
            <iframe
              title="Live browser"
              src={handoff.live_view_url}
              className="aspect-video w-full bg-white"
              sandbox="allow-same-origin allow-scripts allow-forms"
            />
          </div>
        </div>
      )}

      {decided ? (
        <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-amber-200/80">
          <Spinner size="sm" color="warning" />
          {decided === "continue" ? "Continuing…" : "Stopping…"}
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            color="warning"
            radius="full"
            className="font-medium"
            isLoading={pending}
            startContent={
              !pending ? (
                <CheckmarkCircle02Icon className="size-4" />
              ) : undefined
            }
            onPress={() => decide("continue")}
          >
            I've done it — continue
          </Button>
          {handoff.live_view_url && (
            <Button
              as="a"
              href={handoff.live_view_url}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              variant="flat"
              radius="full"
              startContent={<SquareArrowUpRight02Icon className="size-4" />}
            >
              Open full browser
            </Button>
          )}
          <Button
            size="sm"
            variant="light"
            radius="full"
            className="ml-auto text-zinc-400"
            startContent={<StopCircleIcon className="size-4" />}
            onPress={() => decide("cancel")}
          >
            Stop
          </Button>
        </div>
      )}
    </div>
  );
}

export default function BrowserTaskSection({ data }: BrowserTaskSectionProps) {
  const snapshots = useMemo(
    () => (Array.isArray(data) ? data : [data]),
    [data],
  );
  const { session, steps, handoffs, result } = useMemo(
    () => fold(snapshots),
    [snapshots],
  );

  const pendingHandoff = handoffs.find((h) => h.status === "pending");
  const status: UiStatus =
    result?.status ??
    (pendingHandoff ? "paused" : (session?.status ?? "running"));
  const statusMeta = STATUS_META[status];
  const active = !result;
  const working = active && !pendingHandoff;

  return (
    <div className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-2">
        <GlobeIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
        <Chip
          size="sm"
          variant="flat"
          color={statusMeta.color}
          className="ml-auto"
          startContent={
            working ? (
              <Spinner size="sm" color="current" className="mr-1" />
            ) : undefined
          }
        >
          {statusMeta.label}
        </Chip>
      </div>

      {session?.task && (
        <p className="mb-3 text-[13px] leading-snug text-zinc-300">
          {session.task}
        </p>
      )}

      {session?.live_view_url && working && (
        <div className="mb-3">
          <Button
            as="a"
            href={session.live_view_url}
            target="_blank"
            rel="noopener noreferrer"
            size="sm"
            variant="flat"
            radius="full"
            startContent={<EyeIcon className="size-4" />}
          >
            Watch it live
          </Button>
        </div>
      )}

      <div className="space-y-2">
        {steps.map((step) => (
          <StepRow key={`browser-step-${step.index}`} step={step} />
        ))}

        {pendingHandoff && (
          <HandoffPrompt
            key={pendingHandoff.handoff_id}
            handoff={pendingHandoff}
          />
        )}
      </div>

      {result && (
        <>
          <Divider className="my-3 bg-zinc-700/50" />
          <div className="flex items-start gap-2.5">
            {result.success ? (
              <CheckmarkCircle02Icon className="mt-px size-4 shrink-0 text-emerald-400" />
            ) : (
              <Alert01Icon className="mt-px size-4 shrink-0 text-zinc-500" />
            )}
            <p className="text-sm leading-snug text-zinc-200">
              {result.summary}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
