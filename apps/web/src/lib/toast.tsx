"use client";

import { Button } from "@heroui/button";
import { InformationCircleIcon } from "@icons";
import type { ReactNode } from "react";
import { type SileoOptions, type SileoPosition, sileo } from "sileo";

// Mutable holder for a toast's id. sileo returns the id only after the toast is
// created, but dismiss controls (rendered inside the toast) need it on click,
// which happens later — so we bind the id into the holder once it's known.
interface IdRef {
  id: string;
}

// ---------------------------------------------------------------------------
// Sonner-compatible options type
// ---------------------------------------------------------------------------
export interface ToastOptions {
  id?: string;
  description?: ReactNode | string;
  duration?: number;
  icon?: ReactNode;
  action?: {
    label: string;
    onClick: () => void;
  };
  /**
   * Whether to show a default "Dismiss" button when no `action` is provided.
   * Defaults to true so every toast is easy to dismiss. Set false to opt out.
   */
  dismissible?: boolean;
}

const DISMISS_LABEL = "Dismiss";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Sileo's pill title uses white-space: nowrap with a JS-rendered SVG background —
// title cannot wrap. For long messages with no description we promote to description
// so the text wraps properly; sileo falls back to the state name as the pill label.
// When a description is already provided, the title is truncated in the pill.
const TITLE_MAX_CHARS = 50;

type ToastState = "success" | "error" | "warning" | "info" | "loading";

// State-tinted classes for the action button — static so Tailwind compiles them
// and they apply via `className` (HeroUI Button forwards className, not style;
// and sileo's `--_c` var isn't inherited where we render). Reduced-opacity fill
// + matching text, like sileo's own buttons. Dismiss stays neutral.
const ACTION_CLS: Record<ToastState, string> = {
  success: "bg-green-500/15 text-green-400 data-[hover=true]:bg-green-500/25",
  error: "bg-red-500/15 text-red-400 data-[hover=true]:bg-red-500/25",
  warning: "bg-amber-500/15 text-amber-400 data-[hover=true]:bg-amber-500/25",
  info: "bg-sky-500/15 text-sky-400 data-[hover=true]:bg-sky-500/25",
  loading: "bg-white/10 text-white data-[hover=true]:bg-white/15",
};
const DISMISS_CLS = "bg-white/5 text-white/70 data-[hover=true]:bg-white/10";
// rounded-xl (12px) on the 28px-tall button reads as a rounded rectangle; a
// larger radius would exceed half the height and clamp into a full pill.
const BTN_BASE = "h-7 min-w-0 rounded-xl px-3 font-medium text-xs";

// Control row rendered inside the toast description. Sileo's own `button` slot
// only fits ONE button, so we render our own: the action is tinted with the
// toast's state color and dismiss stays neutral. One button spans full width;
// two sit side by side in a 2-column grid. `idRef` resolves the id at click time.
function ToastControls({
  idRef,
  action,
  showDismiss,
  state,
}: Readonly<{
  idRef: IdRef;
  action?: { label: string; onClick: () => void };
  showDismiss: boolean;
  state: ToastState;
}>) {
  const twoUp = !!action && showDismiss;
  return (
    <div className={twoUp ? "mt-2 grid grid-cols-2 gap-2" : "mt-2"}>
      {action ? (
        <Button
          size="sm"
          variant="flat"
          fullWidth
          className={`${BTN_BASE} ${ACTION_CLS[state]}`}
          onPress={action.onClick}
        >
          {action.label}
        </Button>
      ) : null}
      {showDismiss ? (
        <Button
          size="sm"
          variant="flat"
          fullWidth
          className={`${BTN_BASE} ${DISMISS_CLS}`}
          onPress={() => sileo.dismiss(idRef.id)}
        >
          {DISMISS_LABEL}
        </Button>
      ) : null}
    </div>
  );
}

function translate(message: string, opts?: ToastOptions): SileoOptions {
  const out: SileoOptions = {};

  if (message.length > TITLE_MAX_CHARS && opts?.description === undefined) {
    // Long title, no description: move full message to description so it wraps
    out.description = message;
    out.autopilot = true;
    // title intentionally omitted — sileo defaults to state name ("error", "success", etc.)
  } else {
    out.title = message;
    if (opts?.description !== undefined) out.description = opts.description;
  }

  if (opts?.icon !== undefined) out.icon = opts.icon;

  if (opts?.duration === Infinity) {
    // duration: Infinity or omitted null → sticky; otherwise pass through ms
    out.duration = null;
  } else if (opts?.duration !== undefined) {
    out.duration = opts.duration;
  }

  return out;
}

type SileoFn = (opts: SileoOptions) => string;

// Wire up the toast's controls. We deliberately DON'T use sileo's native
// `button` slot — it renders one full-width button. Instead we render our own
// compact, auto-width control row in the description, which keeps buttons small
// and lets an action and a dismiss sit side by side. autopilot makes the panel
// visible (not hover-only). Returns a binder called with sileo's returned id.
function attachControls(
  out: SileoOptions,
  state: ToastState,
  opts?: ToastOptions,
): (id: string) => void {
  const idRef: IdRef = { id: "" };
  const showDismiss = opts?.dismissible !== false;
  const action = opts?.action;

  if (action || showDismiss) {
    out.description = (
      <>
        {out.description}
        <ToastControls
          idRef={idRef}
          action={action}
          showDismiss={showDismiss}
          state={state}
        />
      </>
    );
    out.autopilot = true;
  }

  return (id) => {
    idRef.id = id;
  };
}

function fire(
  fn: SileoFn,
  state: ToastState,
  message: string,
  opts?: ToastOptions,
): string {
  // When an id is passed, dismiss the previous toast first (replace loading → result)
  if (opts?.id) sileo.dismiss(opts.id);
  const out = translate(message, opts);
  const bindId = attachControls(out, state, opts);
  const id = fn(out);
  bindId(id);
  return id;
}

// ---------------------------------------------------------------------------
// Drop-in Sonner-compatible API
// ---------------------------------------------------------------------------
export const toast = {
  success: (message: string, opts?: ToastOptions) =>
    fire(sileo.success, "success", message, opts),

  error: (message: string, opts?: ToastOptions) =>
    fire(sileo.error, "error", message, opts),

  warning: (message: string, opts?: ToastOptions) =>
    fire(sileo.warning, "warning", message, opts),

  info: (message: string, opts?: ToastOptions) =>
    fire(sileo.info, "info", message, {
      ...opts,
      icon: opts?.icon ?? <InformationCircleIcon size={16} />,
    }),

  /** Sticky info toast. Pass the returned id to success/error to replace it. */
  loading: (message: string, opts?: ToastOptions): string => {
    if (opts?.id) sileo.dismiss(opts.id);
    const out: SileoOptions = { ...translate(message, opts), duration: null };
    const bindId = attachControls(out, "loading", opts);
    const id = sileo.info(out);
    bindId(id);
    return id;
  },

  dismiss: (id: string) => sileo.dismiss(id),

  clear: (position?: SileoPosition) => sileo.clear(position),
};
