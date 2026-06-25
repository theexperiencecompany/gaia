"use client";

import type { ChipProps } from "@heroui/chip";
import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  memo,
  type ReactNode,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { MentionChip } from "@/features/integrations/components/MentionChip";
import { useMentionEditor } from "@/features/integrations/hooks/useMentionEditor";
import { MENTION_ATTR } from "@/features/integrations/utils/mentionEditorDom";
import { buildMentionSegments } from "@/features/integrations/utils/toolMentions";

interface MentionEditorProps {
  value: string;
  onChange: (value: string) => void;
  toolNames: string[];
  /** Icon for a given mention name (lets each mention show its own icon). */
  renderMentionIcon?: (name: string) => ReactNode;
  mentionRadius?: ChipProps["radius"];
  placeholder?: string;
  maxLength?: number;
  /** Override the wrapper styling (border/background/radius). */
  className?: string;
  /** Override the editable surface min/max height. */
  surfaceClassName?: string;
  /** Override padding / text size / line height (kept in sync with placeholder). */
  textClassName?: string;
  /** Show the chip's close button. When false, mentions are removed by backspace. */
  mentionRemovable?: boolean;
  /** Render the content but block editing (contentEditable ignores fieldset). */
  readOnly?: boolean;
}

const EDITOR_TEXT = "px-3.5 py-3 text-sm leading-8";
const DEFAULT_WRAPPER =
  "relative rounded-2xl border border-zinc-800 bg-zinc-800/40 transition-colors focus-within:border-zinc-700";
const DEFAULT_SURFACE = "max-h-80 min-h-60";

interface MentionChipTokenProps {
  name: string;
  renderMentionIcon?: (name: string) => ReactNode;
  mentionRadius?: ChipProps["radius"];
  removable?: boolean;
  onRemove: (element: HTMLElement) => void;
}

const MentionChipToken = ({
  name,
  renderMentionIcon,
  mentionRadius,
  removable = true,
  onRemove,
}: MentionChipTokenProps) => {
  const tokenRef = useRef<HTMLSpanElement>(null);
  return (
    <span
      ref={tokenRef}
      {...{ [MENTION_ATTR]: name }}
      contentEditable={false}
      className="mx-0.5 inline-flex translate-y-1 align-baseline"
    >
      <MentionChip
        name={name}
        icon={renderMentionIcon?.(name)}
        radius={mentionRadius}
        onClose={
          removable
            ? () => {
                if (tokenRef.current) onRemove(tokenRef.current);
              }
            : undefined
        }
      />
    </span>
  );
};

interface EditorSurfaceProps {
  epoch: number;
  epochValue: string;
  toolNames: string[];
  rootRef: RefObject<HTMLDivElement | null>;
  renderMentionIcon?: (name: string) => ReactNode;
  mentionRadius?: ChipProps["radius"];
  mentionRemovable?: boolean;
  surfaceClassName: string;
  textClassName: string;
  readOnly?: boolean;
  onRemoveMention: (element: HTMLElement) => void;
  onInput: (event: FormEvent<HTMLDivElement>) => void;
  onBeforeInput: (event: FormEvent<HTMLDivElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onPaste: (event: ClipboardEvent<HTMLDivElement>) => void;
  onSelectionChange: () => void;
  onBlur: () => void;
}

/**
 * The contentEditable surface renders one immutable snapshot per epoch; the
 * memo comparator blocks every re-render in between so React never reconciles
 * DOM the browser has mutated. Structural changes remount it via key={epoch}.
 */
const EditorSurface = memo(
  function EditorSurface({
    epochValue,
    toolNames,
    rootRef,
    renderMentionIcon,
    mentionRadius,
    mentionRemovable,
    surfaceClassName,
    textClassName,
    readOnly,
    onRemoveMention,
    onInput,
    onBeforeInput,
    onKeyDown,
    onPaste,
    onSelectionChange,
    onBlur,
  }: EditorSurfaceProps) {
    const segments = useMemo(
      () => buildMentionSegments(epochValue, toolNames),
      [epochValue, toolNames],
    );

    return (
      // biome-ignore lint/a11y/useSemanticElements: a textarea can't host inline chip elements; textbox is the correct role for a contentEditable editor
      <div
        ref={rootRef}
        role="textbox"
        aria-multiline="true"
        tabIndex={readOnly ? -1 : 0}
        contentEditable={!readOnly}
        suppressContentEditableWarning
        spellCheck={false}
        onInput={onInput}
        onBeforeInput={onBeforeInput}
        onKeyDown={onKeyDown}
        onKeyUp={onSelectionChange}
        onClick={onSelectionChange}
        onPaste={onPaste}
        onBlur={onBlur}
        className={`relative block w-full overflow-y-auto whitespace-pre-wrap break-words text-zinc-100 caret-zinc-100 outline-none ${surfaceClassName} ${textClassName}`}
      >
        {segments.map((segment) =>
          segment.mention ? (
            <MentionChipToken
              key={segment.offset}
              name={segment.text.slice(1)}
              renderMentionIcon={renderMentionIcon}
              mentionRadius={mentionRadius}
              removable={mentionRemovable}
              onRemove={onRemoveMention}
            />
          ) : (
            segment.text
          ),
        )}
        {epochValue.endsWith("\n") && <br />}
      </div>
    );
  },
  (prev, next) => prev.epoch === next.epoch,
);

export const MentionEditor = ({
  value,
  onChange,
  toolNames,
  renderMentionIcon,
  mentionRadius,
  mentionRemovable,
  placeholder,
  maxLength,
  className,
  surfaceClassName,
  textClassName,
  readOnly,
}: MentionEditorProps) => {
  const editor = useMentionEditor({ value, onChange, toolNames, maxLength });
  const textClass = textClassName ?? EDITOR_TEXT;

  // Keep the keyboard-highlighted suggestion visible: the list can hold more
  // items than fit in its max height, so arrowing past the fold must scroll.
  const activeItemRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [editor.highlight, editor.mention]);

  return (
    <div ref={editor.wrapperRef} className={className ?? DEFAULT_WRAPPER}>
      {value.trim() === "" && (
        // Whitespace-only counts as empty: clearing a contentEditable can leave
        // a browser filler <br> (serializes to "\n"), which must still show the
        // placeholder. text-default-500 matches HeroUI's input placeholder.
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute inset-0 whitespace-pre-wrap text-default-500 ${textClass}`}
        >
          {placeholder}
        </div>
      )}

      <EditorSurface
        // Remount on epoch (structural edits) and when the mentionable names
        // load/change, so existing mentions resolve to chips once names arrive.
        key={`${editor.epoch}-${toolNames.length}`}
        epoch={editor.epoch}
        epochValue={editor.epochValue}
        toolNames={toolNames}
        rootRef={editor.rootRef}
        renderMentionIcon={renderMentionIcon}
        mentionRadius={mentionRadius}
        mentionRemovable={mentionRemovable}
        surfaceClassName={surfaceClassName ?? DEFAULT_SURFACE}
        textClassName={textClass}
        readOnly={readOnly}
        onRemoveMention={editor.removeMentionToken}
        onInput={editor.handlers.onInput}
        onBeforeInput={editor.handlers.onBeforeInput}
        onKeyDown={editor.handlers.onKeyDown}
        onPaste={editor.handlers.onPaste}
        onSelectionChange={editor.refreshMention}
        onBlur={editor.closeMention}
      />

      {editor.mention && (
        <ul
          className="absolute z-50 max-h-52 w-64 overflow-y-auto rounded-2xl border border-zinc-700 bg-zinc-900 p-1 shadow-xl"
          style={{
            top: editor.mention.coords.top,
            left: editor.mention.coords.left,
          }}
        >
          {editor.mention.matches.map((name, idx) => (
            <li key={name}>
              <button
                ref={idx === editor.highlight ? activeItemRef : undefined}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.insertMention(name);
                }}
                onMouseEnter={() => editor.setHighlight(idx)}
                className={`flex w-full cursor-pointer items-center gap-2 rounded-xl px-3 py-1.5 text-left text-sm transition-colors ${
                  idx === editor.highlight
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-300"
                }`}
              >
                {renderMentionIcon ? (
                  <span className="inline-flex shrink-0 items-center">
                    {renderMentionIcon(name)}
                  </span>
                ) : null}
                <span className="truncate">{name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
