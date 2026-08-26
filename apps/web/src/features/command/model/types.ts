import type { ReactNode } from "react";

/** The kinds of entities the palette can surface. */
export type CommandItemType =
  | "chat"
  | "message"
  | "workflow"
  | "integration"
  | "todo"
  | "notification"
  | "memory"
  | "page"
  | "action";

/** An inline form an action can open instead of running immediately (e.g. rename). */
export interface CommandActionForm {
  placeholder?: string;
  initialValue?: string;
  submitLabel?: string;
  submit: (value: string) => void | Promise<void>;
}

interface CommandActionBase {
  id: string;
  label: string;
  icon: ReactNode;
  shortcut?: string;
  destructive?: boolean;
}

/**
 * A single runnable action — a row's primary (Enter) or a secondary (Tab
 * menu). Either a one-shot `run` or an inline `form`, never both or neither.
 */
export type CommandAction =
  | (CommandActionBase & {
      run: () => void | Promise<void>;
      form?: never;
    })
  | (CommandActionBase & {
      run?: never;
      form: CommandActionForm;
    });

/** Status dot shown next to a title; meaning conveyed by color + tooltip. */
export interface CommandDot {
  color: "green" | "yellow" | "blue";
  label: string;
}

/** A normalized, presentation-agnostic row. */
export interface CommandItem {
  id: string;
  type: CommandItemType;
  title: string;
  subtitle?: string;
  icon: ReactNode;
  /** Tailwind text-color class applied to the title (e.g. brand-colored rows). */
  tint?: string;
  /** Right-aligned accessory (e.g. a starred marker). */
  accessory?: ReactNode;
  /** Status dot next to the title. */
  dot?: CommandDot;
  /** Extra text folded into search matching. */
  keywords?: string;
  /** Run on Enter / click / number. */
  primary: CommandAction;
  /** Secondary actions (Tab opens the menu). Excludes the primary. */
  actions: CommandAction[];
}

/** How a group behaves at the palette's root level. */
export type CommandGroupKind = "entity" | "actions";

export interface CommandGroup {
  id: string;
  heading: string;
  /** Icon shown on the category row at the root level. */
  icon?: ReactNode;
  /** Tailwind text-color class applied to the category icon (scannability). */
  accent: string;
  kind: CommandGroupKind;
  /** For entity groups: the page to open via the "Go to …" row. */
  path?: string;
  items: CommandItem[];
}

/** Confirm dialog signature, matching useConfirmation's `confirm`. */
export type ConfirmFn = (opts: {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
}) => Promise<boolean>;

/** Capabilities the data layer needs from the host component. */
export interface CommandHost {
  close: () => void;
  confirm: ConfirmFn;
}

/** Shared dependencies passed to every item builder. */
export interface BuildCtx {
  /** Returns a thunk that navigates then closes the palette. */
  navigate: (path: string) => () => void;
  host: CommandHost;
}
