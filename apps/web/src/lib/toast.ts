"use client";

import { InformationCircleIcon } from "@icons";
import React, { type ReactNode } from "react";
import { type SileoOptions, type SileoPosition, sileo } from "sileo";

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
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function translate(message: string, opts?: ToastOptions): SileoOptions {
  const out: SileoOptions = { title: message };

  if (opts?.description !== undefined) out.description = opts.description;
  if (opts?.icon !== undefined) out.icon = opts.icon;

  if (opts?.duration === Infinity) {
    // duration: Infinity or omitted null → sticky; otherwise pass through ms
    out.duration = null;
  } else if (opts?.duration !== undefined) {
    out.duration = opts.duration;
  }

  // Sonner action → Sileo button
  if (opts?.action) {
    out.button = { title: opts.action.label, onClick: opts.action.onClick };
    // Sileo only auto-expands the content panel when a `description` is set.
    // Without autopilot, a button-only panel stays hidden until hover.
    out.autopilot = true;
  }

  return out;
}

type SileoFn = (opts: SileoOptions) => string;

function fire(fn: SileoFn, message: string, opts?: ToastOptions): string {
  // When an id is passed, dismiss the previous toast first (replace loading → result)
  if (opts?.id) sileo.dismiss(opts.id);
  return fn(translate(message, opts));
}

// ---------------------------------------------------------------------------
// Drop-in Sonner-compatible API
// ---------------------------------------------------------------------------
export const toast = {
  success: (message: string, opts?: ToastOptions) =>
    fire(sileo.success, message, opts),

  error: (message: string, opts?: ToastOptions) =>
    fire(sileo.error, message, opts),

  warning: (message: string, opts?: ToastOptions) =>
    fire(sileo.warning, message, opts),

  info: (message: string, opts?: ToastOptions) =>
    fire(sileo.info, message, {
      icon: React.createElement(InformationCircleIcon),
      ...opts,
    }),

  /** Sticky info toast. Pass the returned id to success/error to replace it. */
  loading: (message: string, opts?: ToastOptions): string => {
    if (opts?.id) sileo.dismiss(opts.id);
    return sileo.info({ ...translate(message, opts), duration: null });
  },

  dismiss: (id: string) => sileo.dismiss(id),

  clear: (position?: SileoPosition) => sileo.clear(position),
};
