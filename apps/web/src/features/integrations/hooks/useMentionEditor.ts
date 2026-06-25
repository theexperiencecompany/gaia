import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  getCaretOffset,
  getNodeStartOffset,
  MENTION_ATTR,
  serializeEditorNodes,
  setCaretAtOffset,
} from "@/features/integrations/utils/mentionEditorDom";

// A mention starts at `@` placed at the start of input or after whitespace,
// followed by the query (no spaces / no further `@`).
const MENTION_RE = /(?:^|\s)(@)([^\s@]*)$/;
const MAX_SUGGESTIONS = 8;

interface MentionState {
  query: string;
  matches: string[];
  coords: { top: number; left: number };
}

interface UseMentionEditorParams {
  value: string;
  onChange: (value: string) => void;
  toolNames: string[];
  maxLength?: number;
}

/**
 * State machine for the contentEditable mention editor.
 *
 * The editor renders an immutable snapshot (`epochValue`) per `epoch`; while
 * an epoch is live the browser owns the DOM and every input event serializes
 * it back into the controlled value. Structural changes (chip insert/remove,
 * external resets) bump the epoch, remounting the surface from the new value
 * and restoring the caret by serialized offset.
 */
export const useMentionEditor = ({
  value,
  onChange,
  toolNames,
  maxLength,
}: UseMentionEditorParams) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const [epoch, setEpoch] = useState(0);
  const [epochValue, setEpochValue] = useState(value);
  const lastValueRef = useRef(value);
  const pendingCaretRef = useRef<number | null>(null);

  const [mention, setMention] = useState<MentionState | null>(null);
  const [highlight, setHighlight] = useState(0);

  const toolNamesRef = useRef(toolNames);
  toolNamesRef.current = toolNames;
  const maxLengthRef = useRef(maxLength);
  maxLengthRef.current = maxLength;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const mentionRef = useRef(mention);
  mentionRef.current = mention;
  const highlightRef = useRef(highlight);
  highlightRef.current = highlight;

  // External value change (modal open / reset) → re-render from scratch.
  useEffect(() => {
    if (value !== lastValueRef.current) {
      lastValueRef.current = value;
      setEpochValue(value);
      setEpoch((current) => current + 1);
    }
  }, [value]);

  // Restore focus + caret after a structural remount.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (pendingCaretRef.current === null || !root) return;
    const offset = pendingCaretRef.current;
    pendingCaretRef.current = null;
    root.focus();
    setCaretAtOffset(root, offset);
  }, [epoch]);

  const emit = useCallback((next: string) => {
    lastValueRef.current = next;
    onChangeRef.current(next);
  }, []);

  const commitStructural = useCallback((next: string, caretOffset: number) => {
    lastValueRef.current = next;
    pendingCaretRef.current = caretOffset;
    setEpochValue(next);
    setEpoch((current) => current + 1);
    onChangeRef.current(next);
  }, []);

  const closeMention = useCallback(() => setMention(null), []);

  const refreshMention = useCallback(() => {
    const root = rootRef.current;
    const wrapper = wrapperRef.current;
    const selection = window.getSelection();
    const anchor = selection?.anchorNode;
    if (
      !root ||
      !wrapper ||
      !selection ||
      !anchor ||
      anchor.nodeType !== Node.TEXT_NODE ||
      !root.contains(anchor)
    ) {
      setMention(null);
      return;
    }
    const textBefore = (anchor.textContent ?? "").slice(
      0,
      selection.anchorOffset,
    );
    const match = textBefore.match(MENTION_RE);
    if (!match) {
      setMention(null);
      return;
    }
    const query = match[2];
    const q = query.toLowerCase();
    const pool = q
      ? toolNamesRef.current.filter((name) => name.toLowerCase().includes(q))
      : toolNamesRef.current;
    const matches = pool.slice(0, MAX_SUGGESTIONS);
    if (matches.length === 0) {
      setMention(null);
      return;
    }
    const caretRect = selection.getRangeAt(0).getBoundingClientRect();
    const wrapperRect = wrapper.getBoundingClientRect();
    const previous = mentionRef.current;
    setMention({
      query,
      matches,
      coords: {
        top: caretRect.bottom - wrapperRect.top + 4,
        left: Math.min(
          Math.max(caretRect.left - wrapperRect.left, 0),
          wrapper.clientWidth - 24,
        ),
      },
    });
    // Keep the highlighted suggestion while the same `@query` stays open — this
    // runs on every selection change (incl. the key-up after ArrowUp/Down), so
    // resetting unconditionally would snap the highlight back to the first item
    // and make the dropdown impossible to navigate. Only reset when the query
    // (and thus the match set) actually changes.
    setHighlight((current) =>
      previous && previous.query === query
        ? Math.min(current, matches.length - 1)
        : 0,
    );
  }, []);

  const insertMention = useCallback(
    (name: string) => {
      const root = rootRef.current;
      const current = mentionRef.current;
      if (!root || !current) return;
      const caret = getCaretOffset(root);
      if (caret === null) return;
      const start = caret - current.query.length - 1;
      const token = `@${name} `;
      const base = lastValueRef.current;
      const next = base.slice(0, start) + token + base.slice(caret);
      setMention(null);
      commitStructural(next, start + token.length);
    },
    [commitStructural],
  );

  const removeMentionToken = useCallback(
    (element: HTMLElement) => {
      const root = rootRef.current;
      const name = element.getAttribute(MENTION_ATTR);
      if (!root || !name) return;
      const start = getNodeStartOffset(root, element);
      const base = serializeEditorNodes(root);
      const tokenLength = name.length + 1;
      const trailingSpace = base.charAt(start + tokenLength) === " " ? 1 : 0;
      const next =
        base.slice(0, start) + base.slice(start + tokenLength + trailingSpace);
      setMention(null);
      commitStructural(next, start);
    },
    [commitStructural],
  );

  const onInput = useCallback(
    (_event: FormEvent<HTMLDivElement>) => {
      const root = rootRef.current;
      if (!root) return;
      emit(serializeEditorNodes(root));
      refreshMention();
    },
    [emit, refreshMention],
  );

  const onBeforeInput = useCallback((event: FormEvent<HTMLDivElement>) => {
    const max = maxLengthRef.current;
    if (!max) return;
    const native = event.nativeEvent as InputEvent;
    if (!native.inputType?.startsWith("insert")) return;
    // A selection about to be replaced frees up room, so block only when the
    // post-replacement length would still hit the cap (mirrors onPaste).
    const selectionLength = window.getSelection()?.toString().length ?? 0;
    if (lastValueRef.current.length - selectionLength >= max) {
      event.preventDefault();
    }
  }, []);

  // Keys handled by the open suggestion dropdown; returns true when consumed.
  const handleMentionNavKey = useCallback(
    (event: KeyboardEvent<HTMLDivElement>): boolean => {
      const current = mentionRef.current;
      if (!current) return false;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlight((i) => (i + 1) % current.matches.length);
        return true;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlight(
          (i) => (i - 1 + current.matches.length) % current.matches.length,
        );
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const name =
          current.matches[
            Math.min(highlightRef.current, current.matches.length - 1)
          ];
        if (name) insertMention(name);
        return true;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setMention(null);
        return true;
      }
      return false;
    },
    [insertMention],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      // Let Cmd/Ctrl+Enter bubble so an enclosing form can use it to submit,
      // rather than inserting a line break or accepting a mention.
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") return;
      if (handleMentionNavKey(event)) return;
      if (event.key === "Enter") {
        // Keep line breaks as <br> so serialization stays flat text + "\n".
        event.preventDefault();
        document.execCommand("insertLineBreak");
      }
    },
    [handleMentionNavKey],
  );

  const onPaste = useCallback(
    (event: ClipboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      const root = rootRef.current;
      const selection = window.getSelection();
      if (!root || !selection || selection.rangeCount === 0) return;
      const range = selection.getRangeAt(0);
      if (!root.contains(range.startContainer)) return;
      const pasted = event.clipboardData
        .getData("text/plain")
        .replace(/\r\n/g, "\n");
      const current = serializeEditorNodes(root);
      const selectionLength = range.toString().length;
      const room = maxLengthRef.current
        ? Math.max(0, maxLengthRef.current - (current.length - selectionLength))
        : Number.POSITIVE_INFINITY;
      const text = pasted.slice(0, room);
      if (!text) return;
      range.deleteContents();
      const node = document.createTextNode(text);
      range.insertNode(node);
      range.setStartAfter(node);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      emit(serializeEditorNodes(root));
      refreshMention();
    },
    [emit, refreshMention],
  );

  return {
    rootRef,
    wrapperRef,
    epoch,
    epochValue,
    mention,
    highlight,
    setHighlight,
    insertMention,
    removeMentionToken,
    closeMention,
    refreshMention,
    handlers: { onInput, onBeforeInput, onKeyDown, onPaste },
  };
};
