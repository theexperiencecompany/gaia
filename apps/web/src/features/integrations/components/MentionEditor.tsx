"use client";

import type { ChipProps } from "@heroui/chip";
import type { Extensions } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import { type ReactNode, useEffect, useRef } from "react";
import { buildMentionExtensions } from "@/features/integrations/components/mentionExtensions";
import {
  docToValue,
  valueToContent,
} from "@/features/integrations/utils/mentionDoc";

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
  /** Render the content but block editing. */
  readOnly?: boolean;
}

const EDITOR_TEXT = "px-3.5 py-3 text-sm leading-8";
const DEFAULT_WRAPPER =
  "relative rounded-2xl border border-zinc-800 bg-zinc-800/40 transition-colors focus-within:border-zinc-700";
const DEFAULT_SURFACE = "max-h-80 min-h-60";

/**
 * Plain-text editor with `@<toolName>` mention chips, built on Tiptap. Markdown
 * is authored as literal text; only mentions become atomic nodes. The value is
 * a flat `@<toolName>` string (see {@link valueToContent} / {@link docToValue}),
 * so callers and the backend keep working with plain strings.
 */
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
  const textClass = textClassName ?? EDITOR_TEXT;
  const surfaceClass = surfaceClassName ?? DEFAULT_SURFACE;

  // Live props reach the once-built extensions through refs (Tiptap can't
  // rebuild extensions reactively), so updating them never recreates the editor.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const toolNamesRef = useRef(toolNames);
  toolNamesRef.current = toolNames;
  const iconRef = useRef(renderMentionIcon);
  iconRef.current = renderMentionIcon;
  const removableRef = useRef(mentionRemovable);
  removableRef.current = mentionRemovable;
  const radiusRef = useRef(mentionRadius);
  radiusRef.current = mentionRadius;

  const extensionsRef = useRef<Extensions>(undefined);
  extensionsRef.current ??= buildMentionExtensions(
    {
      icon: iconRef,
      removable: removableRef,
      radius: radiusRef,
      toolNames: toolNamesRef,
    },
    maxLength,
  );

  const editor = useEditor({
    extensions: extensionsRef.current,
    content: valueToContent(value, toolNames),
    editable: !readOnly,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: `block w-full overflow-y-auto whitespace-pre-wrap break-words text-zinc-100 caret-zinc-100 outline-none [&_p]:m-0 ${surfaceClass} ${textClass}`,
      },
    },
    onUpdate: ({ editor: instance }) => {
      onChangeRef.current(docToValue(instance.state.doc));
    },
  });

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  // External value changes (modal open / reset) replace the document — but only
  // on a genuine divergence, never while it already matches. That keeps an
  // in-progress edit from being clobbered and rules out any setContent⇄onChange
  // feedback loop.
  useEffect(() => {
    if (!editor) return;
    if (docToValue(editor.state.doc) === value) return;
    editor.commands.setContent(
      valueToContent(value, toolNamesRef.current),
      false,
    );
  }, [editor, value]);

  // When the tool list loads after mount, re-parse so existing `@name` text
  // resolves into chips — but only on a real change, and never mid-edit.
  const prevToolNamesRef = useRef(toolNames);
  useEffect(() => {
    if (!editor || prevToolNamesRef.current === toolNames) return;
    prevToolNamesRef.current = toolNames;
    if (!editor.isFocused) {
      editor.commands.setContent(valueToContent(value, toolNames), false);
    }
  }, [editor, toolNames, value]);

  return (
    <div className={className ?? DEFAULT_WRAPPER}>
      {value.trim() === "" && (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute inset-0 whitespace-pre-wrap text-default-500 ${textClass}`}
        >
          {placeholder}
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
};
