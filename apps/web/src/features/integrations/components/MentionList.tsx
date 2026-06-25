"use client";

import {
  forwardRef,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

export interface MentionListHandle {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

export interface MentionListProps {
  items: string[];
  command: (name: string) => void;
  renderIcon?: (name: string) => ReactNode;
}

/**
 * Suggestion dropdown for the `@`-mention editor. Tiptap's suggestion utility
 * owns detection and positioning; this component only renders the list and,
 * via the imperative handle, drives keyboard selection (the editor forwards
 * its key events here while the dropdown is open).
 */
export const MentionList = forwardRef<MentionListHandle, MentionListProps>(
  ({ items, command, renderIcon }, ref) => {
    const [selected, setSelected] = useState(0);
    const activeRef = useRef<HTMLButtonElement>(null);

    // A new query yields a new list — start from the top.
    useEffect(() => setSelected(0), [items]);

    // Keep the highlighted item visible when navigating past the fold.
    useEffect(() => {
      activeRef.current?.scrollIntoView({ block: "nearest" });
    }, [selected]);

    useImperativeHandle(
      ref,
      () => ({
        onKeyDown: ({ event }) => {
          if (items.length === 0) return false;
          if (event.key === "ArrowDown") {
            setSelected((i) => (i + 1) % items.length);
            return true;
          }
          if (event.key === "ArrowUp") {
            setSelected((i) => (i - 1 + items.length) % items.length);
            return true;
          }
          if (event.key === "Enter" || event.key === "Tab") {
            const name = items[selected];
            if (name) command(name);
            return true;
          }
          return false;
        },
      }),
      [items, selected, command],
    );

    if (items.length === 0) return null;

    return (
      <ul className="max-h-52 w-64 overflow-y-auto rounded-2xl bg-zinc-900 p-1 shadow-xl">
        {items.map((name, idx) => (
          <li key={name}>
            <button
              ref={idx === selected ? activeRef : undefined}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                command(name);
              }}
              onMouseEnter={() => setSelected(idx)}
              className={`flex w-full cursor-pointer items-center gap-2 rounded-xl px-3 py-1.5 text-left text-sm transition-colors ${
                idx === selected ? "bg-zinc-800 text-zinc-100" : "text-zinc-300"
              }`}
            >
              {renderIcon ? (
                <span className="inline-flex shrink-0 items-center">
                  {renderIcon(name)}
                </span>
              ) : null}
              <span className="truncate">{name}</span>
            </button>
          </li>
        ))}
      </ul>
    );
  },
);

MentionList.displayName = "MentionList";
