"use client";

import type { ChipProps } from "@heroui/chip";
import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  memo,
  type ReactNode,
  type RefObject,
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
  onRemove: (element: HTMLElement) => void;
}

const MentionChipToken = ({
  name,
  renderMentionIcon,
  mentionRadius,
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
        onClose={() => {
          if (tokenRef.current) onRemove(tokenRef.current);
        }}
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
  surfaceClassName: string;
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
    surfaceClassName,
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
        className={`relative block w-full overflow-y-auto whitespace-pre-wrap break-words text-zinc-100 caret-zinc-100 outline-none ${surfaceClassName} ${EDITOR_TEXT}`}
      >
        {segments.map((segment) =>
          segment.mention ? (
            <MentionChipToken
              key={segment.offset}
              name={segment.text.slice(1)}
              renderMentionIcon={renderMentionIcon}
              mentionRadius={mentionRadius}
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
  placeholder,
  maxLength,
  className,
  surfaceClassName,
  readOnly,
}: MentionEditorProps) => {
  const editor = useMentionEditor({ value, onChange, toolNames, maxLength });

  return (
    <div ref={editor.wrapperRef} className={className ?? DEFAULT_WRAPPER}>
      {value === "" && (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute inset-0 whitespace-pre-wrap text-zinc-600 ${EDITOR_TEXT}`}
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
        surfaceClassName={surfaceClassName ?? DEFAULT_SURFACE}
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
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.insertMention(name);
                }}
                onMouseEnter={() => editor.setHighlight(idx)}
                className={`w-full cursor-pointer truncate rounded-xl px-3 py-1.5 text-left text-sm transition-colors ${
                  idx === editor.highlight
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
