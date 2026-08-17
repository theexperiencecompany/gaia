"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Input } from "@heroui/input";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { Spinner } from "@heroui/spinner";
import {
  AiWebBrowsingIcon,
  Alert01Icon,
  CheckmarkCircle02Icon,
  CreditCardIcon,
  CursorInWindowIcon,
  EyeIcon,
  FullScreenIcon,
  ShieldUserIcon,
  SquareArrowUpRight02Icon,
  StopCircleIcon,
} from "@icons";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RecapSlideshow } from "@/components/browser/RecapSlideshow";
import { useImageDialog } from "@/stores/uiStore";
import type {
  BrowserFrameMessage,
  BrowserHandoffSnapshot,
  BrowserHandoffStatus,
  BrowserLiveInputMessage,
  BrowserResultSnapshot,
  BrowserSensitiveCategory,
  BrowserSessionSnapshot,
  BrowserSessionStatus,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "@/types/features/browserTaskTypes";
import {
  browserApi,
  liveViewPageUrl,
  liveViewSocketUrl,
} from "../../../api/browserApi";

interface BrowserTaskSectionProps {
  data: BrowserTaskSnapshot | BrowserTaskSnapshot[];
}

interface FoldedState {
  session?: BrowserSessionSnapshot;
  steps: BrowserStepSnapshot[];
  handoffs: BrowserHandoffSnapshot[];
  result?: BrowserResultSnapshot;
}

type LiveStatus = "connecting" | "live" | "closed" | "error";

const CDP_MOUSE_BUTTONS = ["left", "middle", "right"] as const;

// Streams JPEG frames from the live-view WebSocket onto a canvas and, when
// interactive, forwards pointer/keyboard input as the CDP-shaped messages the
// browser host applies. Kept parallel with the standalone viewer the API serves
// (services/browser/live_view.py) — same event translation, two runtimes.
function useLiveBrowser(socketUrl: string | null, interactive: boolean) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const frameSizeRef = useRef<{ w: number; h: number }>({ w: 1280, h: 720 });
  const [status, setStatus] = useState<LiveStatus>("connecting");

  const send = useCallback((msg: BrowserLiveInputMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    if (!socketUrl) return undefined;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return undefined;

    setStatus("connecting");
    const ws = new WebSocket(socketUrl);
    wsRef.current = ws;
    const img = new window.Image();

    img.onload = () => {
      const w = img.naturalWidth || frameSizeRef.current.w;
      const h = img.naturalHeight || frameSizeRef.current.h;
      frameSizeRef.current = { w, h };
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.drawImage(img, 0, 0, w, h);
    };

    ws.onopen = () => setStatus("live");
    ws.onerror = () => setStatus("error");
    ws.onclose = () => setStatus("closed");
    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: BrowserFrameMessage;
      try {
        msg = JSON.parse(ev.data) as BrowserFrameMessage;
      } catch {
        return;
      }
      if (msg.type === "frame") img.src = `data:image/jpeg;base64,${msg.data}`;
    };

    return () => {
      ws.onopen = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    };
  }, [socketUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!interactive || !socketUrl || !canvas) return undefined;

    const toPoint = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const { w, h } = frameSizeRef.current;
      return {
        x: Math.round((e.clientX - rect.left) * (w / rect.width)),
        y: Math.round((e.clientY - rect.top) * (h / rect.height)),
      };
    };

    const onMove = (e: MouseEvent) => {
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseMoved",
        x: p.x,
        y: p.y,
        buttons: e.buttons,
      });
    };
    const onDown = (e: MouseEvent) => {
      e.preventDefault();
      canvas.focus();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mousePressed",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
      });
    };
    const onUp = (e: MouseEvent) => {
      e.preventDefault();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseReleased",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
      });
    };
    const onContext = (e: MouseEvent) => e.preventDefault();
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseWheel",
        x: p.x,
        y: p.y,
        deltaX: e.deltaX,
        deltaY: e.deltaY,
      });
    };
    const onKeyDown = (e: KeyboardEvent) => {
      e.preventDefault();
      // CDP only fires a key's default action (submit a form, insert a newline)
      // when `text` is set. A single character sends itself; Enter must send the
      // carriage return "\r" or nothing happens — verified against a real page.
      // Other non-printable keys (Tab, Backspace, arrows) act on their virtual
      // key code alone and take no text.
      const text =
        e.key.length === 1 ? e.key : e.key === "Enter" ? "\r" : undefined;
      send({
        type: "key",
        event: "keyDown",
        key: e.key,
        code: e.code,
        text,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
      });
    };
    const onKeyUp = (e: KeyboardEvent) => {
      e.preventDefault();
      send({
        type: "key",
        event: "keyUp",
        key: e.key,
        code: e.code,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
      });
    };

    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mouseup", onUp);
    canvas.addEventListener("contextmenu", onContext);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("keydown", onKeyDown);
    canvas.addEventListener("keyup", onKeyUp);
    return () => {
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("contextmenu", onContext);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("keyup", onKeyUp);
    };
  }, [interactive, socketUrl, send]);

  return { canvasRef, status };
}

// The live view is served from a friendly vhost the host-only session cookie is
// not sent to, so a token is required for every connection. Fetch it once per
// session (cookie auth works same-origin to the API); the token's lifetime
// bounds the socket, which comfortably covers a single browser task.
function useLiveViewToken(sessionId: string | null | undefined): string | null {
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    if (!sessionId) return undefined;
    let active = true;
    browserApi.getLiveViewToken(sessionId).then((res) => {
      if (active && res) setToken(res.token);
    });
    return () => {
      active = false;
    };
  }, [sessionId]);
  return token;
}

function LiveBrowserCanvas({
  socketUrl,
  interactive,
}: {
  socketUrl: string;
  interactive: boolean;
}) {
  const { canvasRef, status } = useLiveBrowser(socketUrl, interactive);
  return (
    <div className="overflow-hidden rounded-xl bg-zinc-950 ring-1 ring-white/10">
      <canvas
        ref={canvasRef}
        tabIndex={interactive ? 0 : -1}
        className={`aspect-video w-full outline-none ${
          interactive ? "cursor-crosshair" : "pointer-events-none"
        }`}
      />
      {status !== "live" && (
        <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-zinc-400">
          <Spinner size="sm" color="current" />
          {status === "error"
            ? "Connection error"
            : status === "closed"
              ? "Session ended"
              : "Connecting…"}
        </div>
      )}
    </div>
  );
}

// Machine states → plain language the user understands at a glance.
const STATUS_META: Record<
  BrowserSessionStatus,
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

// Once the task is done the live session is gone (its live view would 404), so
// the card replays the captured step screenshots instead — a navigable slideshow
// (main frame + prev/next + a filmstrip), the in-card twin of the shared recap
// page (services/browser/replay.py).
function RecapViewer({ steps }: { steps: BrowserStepSnapshot[] }) {
  const shots = useMemo(
    () =>
      steps
        .filter((s) => Boolean(s.screenshot))
        .map((s) => ({
          index: s.index,
          url: s.screenshot as string,
          caption: s.goal,
        })),
    [steps],
  );
  return <RecapSlideshow shots={shots} />;
}

// Resolved elsewhere (chat, another device) or after a reload — server status
// is the source of truth, so the card never sits on a stale "pending".
const RESOLVED_META: Record<
  Exclude<BrowserHandoffStatus, "pending">,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  completed: {
    icon: CheckmarkCircle02Icon,
    label: "Done, resuming the task.",
  },
  cancelled: { icon: StopCircleIcon, label: "Stopped." },
  timeout: { icon: StopCircleIcon, label: "Timed out, the task was stopped." },
};

function HandoffPrompt({ handoff }: { handoff: BrowserHandoffSnapshot }) {
  const [decided, setDecided] = useState<"continue" | "cancel" | null>(null);
  const [pending, setPending] = useState(false);
  const [serverStatus, setServerStatus] = useState<BrowserHandoffStatus | null>(
    null,
  );
  const [note, setNote] = useState("");
  // The primary action starts as "open the full browser"; only once the user has
  // actually opened it does the confirm ("Done") make sense as the next step.
  const [opened, setOpened] = useState(false);
  const meta = HANDOFF_META[handoff.category] ?? HANDOFF_META.none;
  const Icon = meta.icon;
  const liveToken = useLiveViewToken(handoff.session_id);
  const pageUrl =
    handoff.live_view_url && liveToken
      ? liveViewPageUrl(handoff.live_view_url, liveToken)
      : null;
  const hasNote = note.trim().length > 0;

  const settled = serverStatus && serverStatus !== "pending";

  useEffect(() => {
    if (decided || settled) return;
    let active = true;
    const poll = async () => {
      const res = await browserApi.getHandoffStatus(handoff.handoff_id);
      if (active && res && res.status !== "pending")
        setServerStatus(res.status);
    };
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [decided, settled, handoff.handoff_id]);

  const decide = async (decision: "continue" | "cancel", message?: string) => {
    setPending(true);
    setDecided(decision);
    try {
      await browserApi.postHandoffDecision(
        handoff.handoff_id,
        decision,
        message,
      );
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
          <p className="text-sm font-semibold text-amber-50">{meta.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-amber-200/60">
            {handoff.reason}
          </p>
        </div>
      </div>

      {handoff.live_view_url && liveToken && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center gap-1.5 px-0.5">
            <CursorInWindowIcon className="size-3.5 text-amber-300/70" />
            <span className="text-[11px] font-medium text-amber-200/60">
              Live browser, you're in control
            </span>
          </div>
          <LiveBrowserCanvas
            socketUrl={liveViewSocketUrl(handoff.live_view_url, liveToken)}
            interactive
          />
        </div>
      )}

      {decided ? (
        <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-amber-200/80">
          <Spinner size="sm" color="warning" />
          {decided === "continue" ? "Continuing…" : "Stopping…"}
        </div>
      ) : serverStatus && serverStatus !== "pending" ? (
        (() => {
          const resolved = RESOLVED_META[serverStatus];
          const ResolvedIcon = resolved.icon;
          return (
            <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-amber-200/80">
              <ResolvedIcon className="size-4" />
              {resolved.label}
            </div>
          );
        })()
      ) : (
        <div className="mt-3 space-y-2.5 border-t border-amber-500/15 pt-3">
          {!opened && pageUrl ? (
            <Button
              as="a"
              href={pageUrl}
              target="_blank"
              rel="noopener noreferrer"
              color="warning"
              radius="full"
              className="w-full font-semibold"
              endContent={<SquareArrowUpRight02Icon className="size-4" />}
              onPress={() => setOpened(true)}
            >
              Open the browser to sign in
            </Button>
          ) : (
            <Button
              color="warning"
              radius="full"
              className="w-full font-semibold"
              isLoading={pending}
              startContent={
                !pending ? (
                  <CheckmarkCircle02Icon className="size-4" />
                ) : undefined
              }
              onPress={() => decide("continue", note.trim() || undefined)}
            >
              {hasNote ? "Send note and continue" : "I'm done, continue"}
            </Button>
          )}

          <div className="flex items-center gap-2">
            <Input
              size="sm"
              radius="full"
              value={note}
              onValueChange={setNote}
              isDisabled={pending}
              aria-label="Note for the assistant"
              placeholder={'Or tell me what to do, e.g. "just grab the photo"'}
              classNames={{
                inputWrapper:
                  "bg-black/25 data-[hover=true]:bg-black/35 group-data-[focus=true]:bg-black/35",
                input: "text-amber-50 placeholder:text-amber-200/35",
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  decide("continue", note.trim() || undefined);
                }
              }}
            />
            <Button
              variant="light"
              size="sm"
              radius="full"
              className="shrink-0 text-amber-200/50"
              startContent={<StopCircleIcon className="size-4" />}
              onPress={() => decide("cancel")}
            >
              Stop
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// The same shimmer the chat loading text uses (LoadingIndicator.tsx) — a bright
// sweep over dim-white, so "what it's doing right now" reads identically.
function ShimmerText({ text }: { text: string }) {
  return (
    <span
      className="animate-shine bg-size-[200%_100%] bg-clip-text text-transparent"
      style={{
        backgroundImage:
          "linear-gradient(90deg, rgb(255 255 255 / 0.3) 20%, rgb(255 255 255) 50%, rgb(255 255 255 / 0.3) 80%)",
      }}
    >
      {text}
    </span>
  );
}

// The live browser, in its own surface. Full-screen expands only this preview
// (not the whole card) and keeps the current action captioned at the bottom.
function LivePreview({
  socketUrl,
  pageUrl,
  currentTask,
}: {
  socketUrl: string;
  pageUrl: string;
  currentTask?: string;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  // One socket: the canvas mounts inline OR in the modal, never both at once.
  const canvas = (
    <LiveBrowserCanvas socketUrl={socketUrl} interactive={false} />
  );

  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="mb-2 flex items-center gap-1.5 px-0.5">
        <EyeIcon className="size-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Live preview</span>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          radius="full"
          className="ml-auto size-6 min-w-6 text-zinc-400"
          aria-label="Full screen live preview"
          onPress={() => setFullscreen(true)}
        >
          <FullScreenIcon className="size-4" />
        </Button>
      </div>

      {!fullscreen && canvas}

      <div className="mt-2 px-0.5">
        <Button
          as="a"
          href={pageUrl}
          target="_blank"
          rel="noopener noreferrer"
          size="sm"
          variant="light"
          radius="full"
          className="h-7 px-2 text-xs text-zinc-400"
          startContent={<SquareArrowUpRight02Icon className="size-3.5" />}
        >
          Open full browser
        </Button>
      </div>

      <Modal
        isOpen={fullscreen}
        onOpenChange={setFullscreen}
        size="full"
        scrollBehavior="inside"
      >
        <ModalContent className="bg-zinc-950">
          <ModalBody className="flex flex-col gap-4 p-4 sm:p-6">
            <div className="flex min-h-0 flex-1 items-center justify-center">
              {fullscreen && <div className="w-full max-w-6xl">{canvas}</div>}
            </div>
            {currentTask && (
              <div className="mx-auto w-full max-w-6xl shrink-0 rounded-2xl bg-zinc-900 px-4 py-3 text-sm">
                <ShimmerText text={currentTask} />
              </div>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
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
  const status: BrowserSessionStatus =
    result?.status ??
    (pendingHandoff ? "paused" : (session?.status ?? "running"));
  const statusMeta = STATUS_META[status];
  const active = !result;
  const working = active && !pendingHandoff;
  // Only an active session has an owner — minting a live-view token after it
  // ends 403s ("Not authorized for this session"). Fetch it only while the live
  // view is actually shown; the done state renders the recap instead.
  const liveViewToken = useLiveViewToken(working ? session?.session_id : null);
  // What the agent is doing right now — the latest step's goal, surfaced live
  // on the (collapsed) steps header so the user sees progress without expanding.
  const currentTask = working ? steps[steps.length - 1]?.goal : undefined;

  return (
    <div className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2">
        <AiWebBrowsingIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
        <div className="ml-auto flex items-center gap-1.5">
          {working && (
            <Spinner size="sm" color="current" className="text-[#00bbff]" />
          )}
          <Chip
            size="sm"
            variant="flat"
            color={statusMeta.color}
            // Browser accent is #00bbff — apply it to the live "Working" state.
            classNames={
              working
                ? { base: "!bg-[#00bbff]/15", content: "!text-[#00bbff]" }
                : undefined
            }
          >
            {statusMeta.label}
          </Chip>
        </div>
      </div>

      {session?.task && (
        <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-zinc-400">
          {session.task}
        </p>
      )}

      <div className="mt-3 space-y-3">
        {working && session?.live_view_url && liveViewToken && (
          <LivePreview
            socketUrl={liveViewSocketUrl(session.live_view_url, liveViewToken)}
            pageUrl={liveViewPageUrl(session.live_view_url, liveViewToken)}
            currentTask={currentTask}
          />
        )}

        {result && <RecapViewer steps={steps} />}

        {steps.length > 0 && (
          <Accordion isCompact className="px-0" variant="light">
            <AccordionItem
              key="steps"
              aria-label="Steps"
              title={
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 text-sm font-medium text-zinc-300">
                    Steps
                  </span>
                  <Chip
                    size="sm"
                    variant="flat"
                    classNames={{
                      base: "h-5 bg-zinc-700",
                      content: "px-1.5 text-xs text-zinc-300",
                    }}
                  >
                    {steps.length}
                  </Chip>
                  {currentTask && (
                    <span className="min-w-0 flex-1 truncate text-xs">
                      <ShimmerText text={currentTask} />
                    </span>
                  )}
                </div>
              }
              classNames={{ trigger: "py-2", content: "space-y-2 pb-2" }}
            >
              {steps.map((step) => (
                <StepRow key={`browser-step-${step.index}`} step={step} />
              ))}
            </AccordionItem>
          </Accordion>
        )}

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
