import {
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// A mention starts at `@` placed at the start of input or after whitespace,
// followed by the query (no spaces / no further `@`).
const MENTION_RE = /(?:^|\s)(@)([^\s@]*)$/;
const MAX_SUGGESTIONS = 8;

interface MentionState {
  trigger: string;
  query: string;
  start: number; // index of the trigger char in the text
}

/**
 * Inline `@`/`#` tool-mention autocomplete for a textarea, modeled on the
 * chat composer's slash-command detection. Reads the live DOM element captured
 * from events (so it doesn't depend on how HeroUI forwards refs) and rewrites
 * the controlled value on insert.
 */
export const useToolMention = ({
  onChange,
  toolNames,
}: {
  onChange: (value: string) => void;
  toolNames: string[];
}) => {
  const elRef = useRef<HTMLInputElement | null>(null);
  const caretToApply = useRef<number | null>(null);
  const [mention, setMention] = useState<MentionState | null>(null);
  const [highlight, setHighlight] = useState(0);

  const matches = useMemo(() => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();
    const pool = q
      ? toolNames.filter((name) => name.toLowerCase().includes(q))
      : toolNames;
    return pool.slice(0, MAX_SUGGESTIONS);
  }, [mention, toolNames]);

  const close = useCallback(() => setMention(null), []);

  const detect = useCallback(() => {
    const el = elRef.current;
    if (!el) return;
    const caret = el.selectionStart ?? 0;
    const match = el.value.slice(0, caret).match(MENTION_RE);
    if (!match) {
      setMention(null);
      return;
    }
    setMention({
      trigger: match[1],
      query: match[2],
      start: caret - match[2].length - 1,
    });
    setHighlight(0);
  }, []);

  const insert = useCallback(
    (name: string) => {
      const el = elRef.current;
      if (!el || !mention) return;
      const caret = el.selectionStart ?? el.value.length;
      const token = `${mention.trigger}${name} `;
      const next =
        el.value.slice(0, mention.start) + token + el.value.slice(caret);
      caretToApply.current = mention.start + token.length;
      onChange(next);
      setMention(null);
    },
    [mention, onChange],
  );

  // Restore the caret after a mention insert re-renders the controlled value.
  useEffect(() => {
    const el = elRef.current;
    if (caretToApply.current === null || !el) return;
    const pos = caretToApply.current;
    caretToApply.current = null;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  });

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      elRef.current = e.currentTarget;
      if (!mention || matches.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((i) => (i + 1) % matches.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((i) => (i - 1 + matches.length) % matches.length);
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insert(matches[highlight]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    },
    [mention, matches, highlight, insert, close],
  );

  const onKeyUp = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      elRef.current = e.currentTarget;
      detect();
    },
    [detect],
  );

  const onClick = useCallback(
    (e: MouseEvent<HTMLInputElement>) => {
      elRef.current = e.currentTarget;
      detect();
    },
    [detect],
  );

  // `input` fires for every value change (typing, paste, IME, autofill), so
  // the suggestions stay correct regardless of how the text was entered.
  const onInput = useCallback(
    (e: FormEvent<HTMLInputElement>) => {
      elRef.current = e.currentTarget;
      detect();
    },
    [detect],
  );

  return {
    isOpen: mention !== null && matches.length > 0,
    matches,
    highlight,
    setHighlight,
    insert,
    close,
    textareaHandlers: { onKeyDown, onKeyUp, onClick, onInput },
  };
};
