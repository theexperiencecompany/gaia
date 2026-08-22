"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { SearchIcon } from "@icons";
import { Command } from "cmdk";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { PaletteRow } from "./components/PaletteRow";
import { useChatSearch, useMemorySearch } from "./data/useChatSearch";
import { useCommandData } from "./data/useCommandData";
import { frecencyScore, useFrecencyStore } from "./frecency";
import {
  ANIMATION_CONFIG,
  rowEntrance,
  COMMAND_MENU_STYLES as S,
} from "./model/config";
import {
  buildSections,
  isNumbered,
  type Level,
  type Row,
} from "./model/paletteModel";
import type {
  CommandAction,
  CommandGroup,
  CommandHost,
  CommandItem,
} from "./model/types";
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

/**
 * Client-only analytics for row activation — the server can't see which
 * palette rows a user runs, so this never double-counts backend events.
 * Executions (items/actions/ask) fire command:item_executed; item rows
 * activated while searching additionally count as search:result_clicked.
 */
function trackActivation(row: Row, query: string): void {
  if (row.kind === "item") {
    // Record the pick so frecency can boost this item in future rankings.
    useFrecencyStore.getState().record(row.item.id);
    trackEvent(ANALYTICS_EVENTS.COMMAND_ITEM_EXECUTED, {
      item_type: row.item.type,
    });
    if (query.trim() !== "") {
      trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
        result_type: row.item.type,
      });
    }
  } else if (row.kind === "action" || row.kind === "ask") {
    trackEvent(ANALYTICS_EVENTS.COMMAND_ITEM_EXECUTED, {
      item_type: "action",
    });
  }
}

/** What Enter will do for the highlighted row, phrased for the footer. */
function enterLabel(row?: Row): string {
  switch (row?.kind) {
    case "back":
      return "Go back";
    case "loading":
      return "Searching…";
    case "category":
      return row.group.items.length === 0 ? "Open" : "Browse";
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
    buildSearchMemory,
    askGaia,
  } = useCommandData(host);
  const inputRef = useRef<HTMLInputElement>(null);
  const formInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // One entry per drill-down level; each level remembers the query typed in
  // it, so going back restores what was on screen (not a blank input).
  const [levels, setLevels] = useState<Level[]>([{ query: "" }]);
  const [highlightedId, setHighlightedId] = useState<string>();
  // Drives the list's entrance slide: +1 when going deeper, -1 when going back.
  const [direction, setDirection] = useState<1 | -1>(1);
  const reduced = useReducedMotion() ?? false;
  // Inline form (e.g. rename) — replaces the input while active.
  const [formAction, setFormAction] = useState<CommandAction | null>(null);
  const [formValue, setFormValue] = useState("");

  const depth = levels.length - 1;
  const view = levels[depth].view;
  const query = levels[depth].query;

  /** Update the query of the level currently on screen. */
  const setQuery = useCallback((q: string) => {
    setLevels((ls) => {
      const next = [...ls];
      next[next.length - 1] = { ...next[next.length - 1], query: q };
      return next;
    });
  }, []);

  const frecencyEntries = useFrecencyStore((s) => s.entries);
  const boost = useCallback(
    (item: CommandItem) => frecencyScore(frecencyEntries, item.id) * 3,
    [frecencyEntries],
  );

  const { results: serverResults, isFetching: chatsFetching } =
    useChatSearch(query);
  const { memories: searchedMemories, isFetching: memoriesFetching } =
    useMemorySearch(query);
  const searchChats = useMemo(
    () => (serverResults?.conversations ?? []).map(buildSearchChat),
    [serverResults, buildSearchChat],
  );
  const searchMessages = useMemo(
    () => (serverResults?.messages ?? []).map(buildSearchMessage),
    [serverResults, buildSearchMessage],
  );
  const searchMemories = useMemo(
    () =>
      searchedMemories
        .map(buildSearchMemory)
        .filter((item): item is CommandItem => item !== null),
    [searchedMemories, buildSearchMemory],
  );
  const searchLoading = chatsFetching || memoriesFetching;

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
        searchMemories,
        searchLoading,
        boost,
      }),
    [
      view,
      query,
      groups,
      recent,
      context,
      searchChats,
      searchMessages,
      searchMemories,
      searchLoading,
      boost,
    ],
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
  // Position of each row in the flat list — drives the staggered entrance.
  const rowIndex = useMemo(
    () => new Map(flatRows.map((r, i) => [r.id, i] as const)),
    [flatRows],
  );

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
  }, [query, depth]);

  // Mounted only while open: fire the open event, and restore focus on close.
  // The opener is captured by the store's open action — before this mounts and
  // the palette input auto-focuses — so cleanup returns focus to the trigger.
  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SEARCH_GLOBAL_OPENED);
    return () => useCommandMenuStore.getState().openedFrom?.focus();
  }, []);

  const drillCategory = useCallback((groupId: string) => {
    setDirection(1);
    setLevels((ls) => [
      ...ls,
      { view: { level: "category", groupId }, query: "" },
    ]);
  }, []);
  const drillItem = useCallback((item: CommandItem) => {
    setDirection(1);
    setLevels((ls) => [...ls, { view: { level: "item", item }, query: "" }]);
  }, []);
  const back = useCallback(() => {
    setDirection(-1);
    setLevels((ls) => (ls.length > 1 ? ls.slice(0, -1) : ls));
  }, []);
  const goToDepth = (target: number) => {
    setDirection(-1);
    setLevels((ls) => ls.slice(0, target + 1));
  };

  // An empty entity category (e.g. workflows/integrations not yet fetched) has
  // nothing to drill into — open its page directly instead of an empty list.
  const activateCategory = useCallback(
    (group: CommandGroup) => {
      if (group.items.length === 0 && group.path) {
        router.push(group.path);
        close();
      } else {
        drillCategory(group.id);
      }
    },
    [router, close, drillCategory],
  );

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
      trackActivation(row, query);
      switch (row.kind) {
        case "back":
          back();
          break;
        case "category":
          activateCategory(row.group);
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
    [back, activateCategory, runAction, router, close, askGaia, query],
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
      else if (row.kind === "category") activateCategory(row.group);
    },
    [drillItem, activateCategory],
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
        depth ? back() : close();
        return;
      }
      if (event.key === "Tab" && canDrill(highlighted)) {
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
      if (wantsBack && depth) {
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
      depth,
      activate,
      openSecondary,
      back,
      close,
    ],
  );

  const crumbs = levels.slice(1).map((l, i) => {
    const view = l.view;
    return {
      key:
        view?.level === "category"
          ? `cat:${view.groupId}`
          : view?.level === "item"
            ? `item:${view.item.id}`
            : `level:${i}`,
      label:
        view?.level === "category"
          ? (groups.find((g) => g.id === view.groupId)?.heading ?? "")
          : view?.level === "item"
            ? view.item.title
            : "",
      depth: i + 1,
    };
  });

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
              <Input
                ref={formInputRef}
                value={formValue}
                onValueChange={setFormValue}
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
                aria-label={formAction.label}
                variant="flat"
                // Bare, borderless field so it sits in the palette header
                // exactly like the search input it temporarily replaces.
                classNames={{
                  inputWrapper:
                    "h-auto min-h-0 bg-transparent p-0 shadow-none data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent",
                  input: `${S.input} text-sm`,
                }}
              />
            </div>
          ) : (
            <div className={S.inputWrapper}>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={() => goToDepth(0)}
                aria-label="Back to top"
                className="h-auto w-auto min-w-0 shrink-0 text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
              >
                <SearchIcon className="h-4 w-4" />
              </Button>
              {crumbs.map((crumb) => (
                <span
                  key={crumb.key}
                  className="flex shrink-0 items-center gap-2 text-sm text-zinc-400"
                >
                  <Button
                    size="sm"
                    variant="light"
                    onPress={() => goToDepth(crumb.depth)}
                    className="h-auto min-w-0 max-w-[180px] rounded-none p-0 text-sm text-zinc-400 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-200"
                  >
                    <span className="truncate">{crumb.label}</span>
                  </Button>
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
              {noResults && (
                <div className="flex flex-col items-center gap-2 py-6 text-zinc-500">
                  <SearchIcon className="h-6 w-6 text-zinc-600" />
                  <p className="text-sm">No results for "{query.trim()}"</p>
                </div>
              )}
              {/* Keyed by depth so moving between levels remounts the list and
                  replays the entrance slide; typing within a level does not. */}
              <div key={depth}>
                {sections.map((section, index) => (
                  <CommandSection
                    key={section.id}
                    heading={section.heading}
                    showSeparator={index > 0}
                  >
                    {section.rows.map((row) => (
                      <m.div
                        key={row.id}
                        {...rowEntrance({
                          index: rowIndex.get(row.id) ?? 0,
                          direction,
                          browsing: query.trim() === "",
                          reduced,
                        })}
                      >
                        <PaletteRow
                          row={row}
                          number={numbered.get(row.id)}
                          onActivate={() => activate(row)}
                          onSecondary={() => openSecondary(row)}
                        />
                      </m.div>
                    ))}
                  </CommandSection>
                ))}
              </div>
            </Command.List>
          )}

          <div className={`${S.footer} flex items-center gap-4`}>
            {formAction ? (
              <>
                <Hint
                  k={<Kbd keys={["enter"]} />}
                  label={formAction.form?.submitLabel ?? "Save"}
                />
                <Hint k={<Kbd>esc</Kbd>} label="Cancel" />
              </>
            ) : (
              <>
                <Hint
                  k={<Kbd keys={["enter"]} />}
                  label={enterLabel(highlighted)}
                />
                {showActionsHint && <Hint k={<Kbd>Tab</Kbd>} label="Actions" />}
                <Hint k={<Kbd>esc</Kbd>} label={depth ? "Back" : "Close"} />
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
