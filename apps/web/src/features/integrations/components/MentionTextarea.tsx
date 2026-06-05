"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useToolMention } from "@/features/integrations/hooks/useToolMention";
import { getCaretCoordinates } from "@/features/integrations/utils/caretCoordinates";

interface MentionTextareaProps {
  value: string;
  onChange: (value: string) => void;
  toolNames: string[];
  placeholder?: string;
  maxLength?: number;
  rows?: number;
}

interface Segment {
  text: string;
  mention: boolean;
  offset: number;
}

// Split the text on `@<toolName>` occurrences so they can be highlighted in the
// backdrop. Longest names first so e.g. "@Send Email" wins over "@Send".
const buildSegments = (value: string, toolNames: string[]): Segment[] => {
  if (toolNames.length === 0)
    return [{ text: value, mention: false, offset: 0 }];
  const alternation = toolNames
    .slice()
    .sort((a, b) => b.length - a.length)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`))
    .join("|");
  // Trailing boundary so a prefix doesn't highlight inside a longer token
  // (e.g. "@Send" must not light up inside "@Sender").
  const re = new RegExp(String.raw`@(?:${alternation})(?!\w)`, "g");
  const segments: Segment[] = [];
  let last = 0;
  for (const match of value.matchAll(re)) {
    const index = match.index ?? 0;
    if (index > last)
      segments.push({
        text: value.slice(last, index),
        mention: false,
        offset: last,
      });
    segments.push({ text: match[0], mention: true, offset: index });
    last = index + match[0].length;
  }
  if (last < value.length)
    segments.push({ text: value.slice(last), mention: false, offset: last });
  return segments;
};

const SHARED_TEXT = "px-3 py-2 font-mono text-sm leading-relaxed";

export const MentionTextarea = ({
  value,
  onChange,
  toolNames,
  placeholder,
  maxLength,
  rows = 10,
}: MentionTextareaProps) => {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const mention = useToolMention({ taRef, onChange, toolNames });
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(
    null,
  );

  const segments = useMemo(
    () => buildSegments(value, toolNames),
    [value, toolNames],
  );

  // Anchor the suggestion list to the caret as the query changes.
  useEffect(() => {
    const el = taRef.current;
    if (!mention.isOpen || !el) {
      setCoords(null);
      return;
    }
    const caret = getCaretCoordinates(el, el.selectionStart ?? 0);
    setCoords({
      top: caret.top - el.scrollTop + caret.height + 4,
      left: Math.min(caret.left - el.scrollLeft, el.clientWidth - 24),
    });
  }, [mention.isOpen, mention.matches, value]);

  const syncScroll = () => {
    if (backdropRef.current && taRef.current) {
      backdropRef.current.scrollTop = taRef.current.scrollTop;
      backdropRef.current.scrollLeft = taRef.current.scrollLeft;
    }
  };

  return (
    <div className="relative rounded-2xl border border-zinc-800 bg-zinc-800/40 transition-colors focus-within:border-zinc-700">
      <div
        ref={backdropRef}
        aria-hidden="true"
        className={`pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-zinc-100 ${SHARED_TEXT}`}
      >
        {segments.map((segment) =>
          segment.mention ? (
            <mark
              key={segment.offset}
              className="rounded bg-primary/20 text-primary"
            >
              {segment.text}
            </mark>
          ) : (
            <span key={segment.offset}>{segment.text}</span>
          ),
        )}
      </div>

      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onInput={mention.refresh}
        onKeyUp={mention.refresh}
        onClick={mention.refresh}
        onKeyDown={mention.onKeyDown}
        onScroll={syncScroll}
        onBlur={mention.close}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        spellCheck={false}
        className={`relative block w-full resize-none bg-transparent text-transparent caret-zinc-100 outline-none placeholder:text-zinc-600 ${SHARED_TEXT}`}
      />

      {mention.isOpen && coords && (
        <ul
          className="absolute z-50 max-h-52 w-64 overflow-y-auto rounded-2xl border border-zinc-700 bg-zinc-900 p-1 shadow-xl"
          style={{ top: coords.top, left: coords.left }}
        >
          {mention.matches.map((name, idx) => (
            <li key={name}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  mention.insert(name);
                }}
                onMouseEnter={() => mention.setHighlight(idx)}
                className={`w-full truncate rounded-xl px-3 py-1.5 text-left text-sm transition-colors ${
                  idx === mention.highlight
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-300"
                }`}
              >
                {name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
