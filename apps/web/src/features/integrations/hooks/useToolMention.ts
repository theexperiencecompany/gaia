import {
  type KeyboardEvent,
  type RefObject,
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
  query: string;
  start: number; // index of the `@` in the text
}

/**
 * Inline `@` tool-mention autocomplete for a textarea. Detection is driven by
 * the live DOM element (via the passed ref) so it stays correct regardless of
 * how the text was entered, and inserting rewrites the controlled value.
 */
export const useToolMention = ({
  taRef,
  onChange,
  toolNames,
}: {
  taRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  toolNames: string[];
}) => {
  const [mention, setMention] = useState<MentionState | null>(null);
  const [highlight, setHighlight] = useState(0);
  const caretToApply = useRef<number | null>(null);

  const matches = useMemo(() => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();
    const pool = q
      ? toolNames.filter((name) => name.toLowerCase().includes(q))
      : toolNames;
    return pool.slice(0, MAX_SUGGESTIONS);
  }, [mention, toolNames]);

  const close = useCallback(() => setMention(null), []);

  const refresh = useCallback(() => {
    const el = taRef.current;
    if (!el) return;
    const caret = el.selectionStart ?? 0;
    const match = el.value.slice(0, caret).match(MENTION_RE);
    if (!match) {
      setMention(null);
      return;
    }
    setMention({ query: match[2], start: caret - match[2].length - 1 });
    setHighlight(0);
  }, [taRef]);

  const insert = useCallback(
    (name: string) => {
      const el = taRef.current;
      if (!el || !mention) return;
      const caret = el.selectionStart ?? el.value.length;
      const token = `@${name} `;
      const next =
        el.value.slice(0, mention.start) + token + el.value.slice(caret);
      caretToApply.current = mention.start + token.length;
      onChange(next);
      setMention(null);
    },
    [mention, onChange, taRef],
  );

  // Restore the caret after a mention insert re-renders the controlled value.
  useEffect(() => {
    const el = taRef.current;
    if (caretToApply.current === null || !el) return;
    const pos = caretToApply.current;
    caretToApply.current = null;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  });

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
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

  return {
    isOpen: mention !== null && matches.length > 0,
    matches,
    highlight,
    setHighlight,
    insert,
    close,
    refresh,
    onKeyDown,
  };
};
