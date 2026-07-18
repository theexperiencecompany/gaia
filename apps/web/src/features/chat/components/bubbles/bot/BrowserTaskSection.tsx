"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Link } from "@heroui/link";
import { Spinner } from "@heroui/spinner";
import {
  Alert01Icon,
  CheckmarkCircle02Icon,
  CreditCardIcon,
  GlobeIcon,
  ShieldUserIcon,
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

const STATUS_COLOR: Record<
  BrowserSessionStatus | "paused",
  "default" | "primary" | "success" | "danger" | "warning"
> = {
  starting: "default",
  running: "primary",
  paused: "warning",
  completed: "success",
  failed: "danger",
  cancelled: "default",
};

const CATEGORY_ICON: Record<
  BrowserSensitiveCategory,
  React.ComponentType<{ className?: string }>
> = {
  none: Alert01Icon,
  payment: CreditCardIcon,
  credentials: ShieldUserIcon,
  irreversible: Alert01Icon,
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
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs text-zinc-400">
          {step.index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-zinc-200">{step.goal}</p>
          {step.action && (
            <p className="mt-0.5 truncate text-xs text-zinc-500">
              {step.action}
            </p>
          )}
          {step.url && (
            <p className="mt-0.5 truncate text-xs text-zinc-600">{step.url}</p>
          )}
        </div>
      </div>
      {step.screenshot && (
        <button
          type="button"
          onClick={() => openDialog(step.screenshot as string)}
          className="mt-2 block w-full overflow-hidden rounded-xl"
        >
          <Image
            src={step.screenshot}
            alt={`Step ${step.index} screenshot`}
            width={1280}
            height={720}
            className="h-auto w-full rounded-xl"
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
  const Icon = CATEGORY_ICON[handoff.category] ?? Alert01Icon;

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
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-zinc-200">
            I need you to take over for this step.
          </p>
          <p className="mt-0.5 text-xs text-zinc-400">{handoff.reason}</p>
        </div>
      </div>

      {handoff.live_view_url && (
        <div className="mt-3 overflow-hidden rounded-xl border border-zinc-700/50">
          <iframe
            title="Live browser"
            src={handoff.live_view_url}
            className="aspect-video w-full"
            sandbox="allow-same-origin allow-scripts allow-forms"
          />
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button
          size="sm"
          color="primary"
          radius="full"
          isLoading={pending && decided === "continue"}
          isDisabled={decided !== null}
          onPress={() => decide("continue")}
        >
          I'm done — continue
        </Button>
        <Button
          size="sm"
          variant="flat"
          radius="full"
          isDisabled={decided !== null}
          onPress={() => decide("cancel")}
        >
          Cancel
        </Button>
        {handoff.live_view_url && (
          <Link
            href={handoff.live_view_url}
            isExternal
            size="sm"
            className="ml-auto text-xs"
          >
            Open in new tab
          </Link>
        )}
      </div>
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
  const status: BrowserSessionStatus | "paused" =
    result?.status ??
    (pendingHandoff ? "paused" : (session?.status ?? "running"));
  const active = !result;

  return (
    <div className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        <GlobeIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
        <Chip
          size="sm"
          variant="flat"
          color={STATUS_COLOR[status]}
          className="ml-auto"
        >
          {status}
        </Chip>
        {active && !pendingHandoff && <Spinner size="sm" color="current" />}
      </div>

      {session?.task && (
        <p className="mb-3 text-xs text-zinc-400">{session.task}</p>
      )}

      {session?.live_view_url && active && !pendingHandoff && (
        <Link
          href={session.live_view_url}
          isExternal
          size="sm"
          className="mb-3 text-xs"
        >
          Watch live
        </Link>
      )}

      <div className="space-y-2">
        {steps.map((step) => (
          <StepRow key={`browser-step-${step.index}`} step={step} />
        ))}

        {pendingHandoff && <HandoffPrompt handoff={pendingHandoff} />}
      </div>

      {result && (
        <>
          <Divider className="my-3 bg-zinc-700/50" />
          <div className="flex items-start gap-2">
            {result.success ? (
              <CheckmarkCircle02Icon className="mt-0.5 size-4 shrink-0 text-emerald-400" />
            ) : (
              <Alert01Icon className="mt-0.5 size-4 shrink-0 text-zinc-500" />
            )}
            <p className="text-sm text-zinc-300">{result.summary}</p>
          </div>
        </>
      )}
    </div>
  );
}
