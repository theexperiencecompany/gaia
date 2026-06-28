"use client";

import { Kbd } from "@heroui/kbd";
import { SearchIcon } from "@icons";
import { Command } from "cmdk";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { PaletteRow } from "./components/PaletteRow";
import { useChatSearch } from "./data/useChatSearch";
import { useCommandData } from "./data/useCommandData";
import { ANIMATION_CONFIG, COMMAND_MENU_STYLES as S } from "./model/config";
import {
  buildSections,
  isNumbered,
  type Row,
  type View,
} from "./model/paletteModel";
import type { CommandAction, CommandHost, CommandItem } from "./model/types";
import { useCommandMenuStore } from "./store";

const MAX_NUMBERED = 9;

// 1–9 → the Nth numbered row. Bare digit only when the filter is empty (so a
// digit can still be typed into a query); ⌘/Ctrl+digit always works.
function resolveDigitRow(
  event: React.KeyboardEvent,
  query: string,
  numberedRows: Row[],
): Row | undefined {
  const digit = Number(event.key);
  if (!Number.isInteger(digit) || digit < 1 || digit > MAX_NUMBERED)
    return undefined;
  const withMod = event.metaKey || event.ctrlKey;
  if (!withMod && (query !== "" || event.altKey)) return undefined;
  return numberedRows[digit - 1];
}

const canDrill = (row?: Row): boolean =>
  !!row && (row.kind === "category" || (row.kind === "item" && row.canDrill));

/** What Enter will do for the highlighted row, phrased for the footer. */
function enterLabel(row?: Row): string {
  switch (row?.kind) {
    case "back":
      return "Go back";
    case "category":
      return "Browse";
    case "item":
      return row.item.primary.label;
    case "action":
      return row.action.label;
    case "nav":
      return row.label;
    case "ask":
      return "Ask GAIA";
    default:
      return "Open";
  }
}

export default function CommandMenu({ host }: { host: CommandHost }) {
  const router = useRouter();
  const close = useCommandMenuStore((s) => s.close);
  const {
    groups,
    recent,
    context,
    buildSearchChat,
    buildSearchMessage,
    askGaia,
  } = useCommandData(host);
  const inputRef = useRef<HTMLInputElement>(null);
  const formInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [stack, setStack] = useState<View[]>([]);
  const [query, setQuery] = useState("");
  const [highlightedId, setHighlightedId] = useState<string>();
  // Inline form (e.g. rename) — replaces the input while active.
  const [formAction, setFormAction] = useState<CommandAction | null>(null);
  const [formValue, setFormValue] = useState("");

  const view = stack.at(-1);

  const serverResults = useChatSearch(query);
  const searchChats = useMemo(
    () => (serverResults?.conversations ?? []).map(buildSearchChat),
    [serverResults, buildSearchChat],
  );
  const searchMessages = useMemo(
    () => (serverResults?.messages ?? []).map(buildSearchMessage),
    [serverResults, buildSearchMessage],
  );

  const sections = useMemo(
    () =>
      buildSections({
        view,
        query,
        groups,
        recent,
        context,
        searchChats,
        searchMessages,
      }),
    [view, query, groups, recent, context, searchChats, searchMessages],
  );

  const flatRows = useMemo(() => sections.flatMap((s) => s.rows), [sections]);
  const numberedRows = useMemo(
    () => flatRows.filter(isNumbered).slice(0, MAX_NUMBERED),
    [flatRows],
  );
  const numbered = useMemo(() => {
    const map = new Map<string, number>();
    numberedRows.forEach((r, i) => map.set(r.id, i + 1));
    return map;
  }, [numberedRows]);

  useEffect(() => {
    if (flatRows.length === 0) return;
    if (!flatRows.some((r) => r.id === highlightedId)) {
      setHighlightedId((numberedRows[0] ?? flatRows[0]).id);
    }
  }, [flatRows, numberedRows, highlightedId]);

  // Focus the inline form field when it opens.
  useEffect(() => {
    if (formAction) formInputRef.current?.focus();
  }, [formAction]);

  // Scroll back to the top whenever the query or level changes. rAF so it runs
  // after cmdk's own scroll-the-selection-into-view.
  useEffect(() => {
    const id = requestAnimationFrame(() =>
      listRef.current?.scrollTo({ top: 0 }),
    );
    return () => cancelAnimationFrame(id);
  }, [query, stack.length]);

  // Mounted only while open: fire the open event, and restore focus on close.
  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SEARCH_GLOBAL_OPENED);
    const previouslyFocused = document.activeElement as HTMLElement | null;
    return () => previouslyFocused?.focus?.();
  }, []);

  const drillCategory = useCallback((groupId: string) => {
    setStack((s) => [...s, { level: "category", groupId }]);
    setQuery("");
  }, []);
  const drillItem = useCallback((item: CommandItem) => {
    setStack((s) => [...s, { level: "item", item }]);
    setQuery("");
  }, []);
  const back = useCallback(() => {
    setStack((s) => s.slice(0, -1));
    setQuery("");
  }, []);
  const goToDepth = (depth: number) => {
    setStack((s) => s.slice(0, depth));
    setQuery("");
  };

  const runAction = useCallback((action: CommandAction) => {
    if (action.form) {
      setFormAction(action);
      setFormValue(action.form.initialValue ?? "");
    } else {
      void action.run?.();
    }
  }, []);

  const activate = useCallback(
    (row: Row) => {
      switch (row.kind) {
        case "back":
          back();
          break;
        case "category":
          drillCategory(row.group.id);
          break;
        case "item":
          runAction(row.item.primary);
          break;
        case "action":
          runAction(row.action);
          break;
        case "nav":
          router.push(row.path);
          close();
          break;
        case "ask":
          askGaia(row.query);
          break;
      }
    },
    [back, drillCategory, runAction, router, close, askGaia],
  );

  const submitForm = useCallback(async () => {
    if (!formAction?.form) return;
    try {
      await formAction.form.submit(formValue);
      close(); // builder toasts on error; only close on success
    } catch {
      // keep the form open so the user can retry
    }
  }, [formAction, formValue, close]);

  const openSecondary = useCallback(
    (row: Row | undefined) => {
      if (!row) return;
      if (row.kind === "item" && row.canDrill) drillItem(row.item);
      else if (row.kind === "category") drillCategory(row.group.id);
    },
    [drillItem, drillCategory],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (formAction) return; // the inline form input handles its own keys
      const el = inputRef.current;
      const caretAtEnd = !el || el.selectionStart === el.value.length;
      const caretAtStart =
        !el || (el.selectionStart === 0 && el.selectionEnd === 0);
      const highlighted = flatRows.find((r) => r.id === highlightedId);

      const digitRow = resolveDigitRow(event, query, numberedRows);
      if (digitRow) {
        event.preventDefault();
        activate(digitRow);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        stack.length ? back() : close();
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        openSecondary(highlighted);
        return;
      }
      if (event.key === "ArrowRight" && caretAtEnd && canDrill(highlighted)) {
        event.preventDefault();
        openSecondary(highlighted);
        return;
      }
      const wantsBack =
        (event.key === "ArrowLeft" && caretAtStart) ||
        (event.key === "Backspace" && query === "");
      if (wantsBack && stack.length) {
        event.preventDefault();
        back();
      }
    },
    [
      formAction,
      flatRows,
      highlightedId,
      query,
      numberedRows,
      stack,
      activate,
      openSecondary,
      back,
      close,
    ],
  );

  const crumbs = stack.map((v, i) => ({
    key: v.level === "category" ? `cat:${v.groupId}` : `item:${v.item.id}`,
    label:
      v.level === "category"
        ? (groups.find((g) => g.id === v.groupId)?.heading ?? "")
        : v.item.title,
    depth: i + 1,
  }));

  const placeholder = view ? "Filter..." : "Search or jump to...";
  const noResults =
    query.trim() !== "" && flatRows.every((r) => r.kind === "ask");
  const highlighted = flatRows.find((r) => r.id === highlightedId);
  const showActionsHint = highlighted?.kind === "item" && highlighted.canDrill;

  return (
    <div className={S.modalWrapper}>
      <m.div
        {...ANIMATION_CONFIG.backdrop}
        className={S.backdrop}
        onClick={() => close()}
      />
      <m.div
        {...ANIMATION_CONFIG.container}
        className={S.container}
        role="dialog"
        aria-modal="true"
        aria-label="Command menu"
      >
        <Command
          shouldFilter={false}
          loop
          value={highlightedId}
          onValueChange={setHighlightedId}
          onKeyDown={handleKeyDown}
          className={S.groupHeadings}
        >
          {formAction ? (
            <div className={S.inputWrapper}>
              {formAction.icon}
              <span className="shrink-0 text-sm text-zinc-400">
                {formAction.label}
              </span>
              <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
              <input
                ref={formInputRef}
                value={formValue}
                onChange={(e) => setFormValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void submitForm();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setFormAction(null);
                  }
                }}
                placeholder={formAction.form?.placeholder}
                className={`${S.input} text-sm`}
              />
            </div>
          ) : (
            <div className={S.inputWrapper}>
              <button
                type="button"
                onClick={() => goToDepth(0)}
                aria-label="Back to top"
                className="shrink-0 text-zinc-500 transition-colors hover:text-zinc-300"
              >
                <SearchIcon className="h-4 w-4" />
              </button>
              {crumbs.map((crumb) => (
                <span
                  key={crumb.key}
                  className="flex shrink-0 items-center gap-2 text-sm text-zinc-400"
                >
                  <button
                    type="button"
                    onClick={() => goToDepth(crumb.depth)}
                    className="max-w-[180px] cursor-pointer truncate transition-colors hover:text-zinc-200"
                  >
                    {crumb.label}
                  </button>
                  <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
                </span>
              ))}
              <Command.Input
                ref={inputRef}
                autoFocus
                value={query}
                onValueChange={setQuery}
                placeholder={placeholder}
                className={`${S.input} text-sm`}
              />
            </div>
          )}

          {!formAction && (
            <Command.List ref={listRef} className={S.list}>
              <Command.Empty className={S.empty}>
                No results found.
              </Command.Empty>
              {noResults && (
                <div className="flex flex-col items-center gap-2 py-6 text-zinc-500">
                  <SearchIcon className="h-6 w-6 text-zinc-600" />
                  <p className="text-sm">No results for "{query.trim()}"</p>
                </div>
              )}
              {sections.map((section, index) => (
                <CommandSection
                  key={section.id}
                  heading={section.heading}
                  showSeparator={index > 0}
                >
                  {section.rows.map((row) => (
                    <PaletteRow
                      key={row.id}
                      row={row}
                      number={numbered.get(row.id)}
                      onActivate={() => activate(row)}
                      onSecondary={() => openSecondary(row)}
                    />
                  ))}
                </CommandSection>
              ))}
            </Command.List>
          )}

          <div className={`${S.footer} flex items-center gap-4`}>
            {formAction ? (
              <>
                <Hint k={<Kbd keys={["enter"]} />} label="Save" />
                <Hint k={<Kbd>esc</Kbd>} label="Cancel" />
              </>
            ) : (
              <>
                <Hint
                  k={<Kbd keys={["enter"]} />}
                  label={enterLabel(highlighted)}
                />
                {showActionsHint && <Hint k={<Kbd>Tab</Kbd>} label="Actions" />}
                <Hint
                  k={<Kbd>esc</Kbd>}
                  label={stack.length ? "Back" : "Close"}
                />
              </>
            )}
          </div>
        </Command>
      </m.div>
    </div>
  );
}

function CommandSection({
  heading,
  showSeparator,
  children,
}: {
  heading?: string;
  showSeparator: boolean;
  children: React.ReactNode;
}) {
  return (
    <>
      {showSeparator && <Command.Separator className={S.separator} />}
      <Command.Group heading={heading}>{children}</Command.Group>
    </>
  );
}

function Hint({ k, label }: { k: React.ReactNode; label: string }) {
  return (
    <span className={`${S.footerText} flex items-center gap-1.5`}>
      {k} {label}
    </span>
  );
}
