"use client";

import type { ChipProps } from "@heroui/chip";
import type { Extensions } from "@tiptap/core";
import CharacterCount from "@tiptap/extension-character-count";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import History from "@tiptap/extension-history";
import Mention, { type MentionNodeAttrs } from "@tiptap/extension-mention";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import {
  type NodeViewProps,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  ReactRenderer,
} from "@tiptap/react";
import type {
  SuggestionKeyDownProps,
  SuggestionProps,
} from "@tiptap/suggestion";
import type { MutableRefObject, ReactNode } from "react";
import { MentionChip } from "@/features/integrations/components/MentionChip";
import {
  MentionList,
  type MentionListHandle,
  type MentionListProps,
} from "@/features/integrations/components/MentionList";

const MAX_SUGGESTIONS = 8;

/** A selected mention carries the tool name as both its id and display label. */
type SuggestionItem = string;
type Suggestion = SuggestionProps<SuggestionItem, MentionNodeAttrs>;

/**
 * Live editor props funneled into the extensions through refs. Tiptap builds
 * its extensions once, so the suggestion list and chip node-view read the
 * current values here instead of forcing the editor to rebuild on prop change.
 */
export interface MentionExtensionRefs {
  icon: MutableRefObject<((name: string) => ReactNode) | undefined>;
  removable: MutableRefObject<boolean | undefined>;
  radius: MutableRefObject<ChipProps["radius"] | undefined>;
  toolNames: MutableRefObject<string[]>;
}

/** Renders an inserted mention as the shared HeroUI chip (with its icon). */
const createMentionNodeView = (refs: MentionExtensionRefs) =>
  function MentionNodeView({ node, deleteNode }: NodeViewProps) {
    const name = (node.attrs.label ?? node.attrs.id ?? "") as string;
    return (
      <NodeViewWrapper
        as="span"
        className="mx-0.5 inline-flex translate-y-1 align-baseline"
      >
        <MentionChip
          name={name}
          icon={refs.icon.current?.(name)}
          radius={refs.radius.current}
          onClose={refs.removable.current ? () => deleteNode() : undefined}
        />
      </NodeViewWrapper>
    );
  };

/** The `@`-suggestion dropdown: mounts {@link MentionList} at the caret. */
const createSuggestionRenderer = (refs: MentionExtensionRefs) => () => {
  let renderer: ReactRenderer<MentionListHandle, MentionListProps> | null =
    null;
  let container: HTMLDivElement | null = null;

  const place = (rect?: (() => DOMRect | null) | null) => {
    const box = rect?.();
    if (!container || !box) return;
    container.style.top = `${box.bottom + 4}px`;
    container.style.left = `${box.left}px`;
  };

  const listProps = (props: Suggestion): MentionListProps => ({
    items: props.items,
    command: (name) => props.command({ id: name, label: name }),
    renderIcon: refs.icon.current,
  });

  const destroy = () => {
    renderer?.destroy();
    container?.remove();
    renderer = null;
    container = null;
  };

  return {
    onStart: (props: Suggestion) => {
      renderer = new ReactRenderer(MentionList, {
        editor: props.editor,
        props: listProps(props),
      });
      container = document.createElement("div");
      container.style.position = "fixed";
      container.style.zIndex = "70";
      document.body.appendChild(container);
      container.appendChild(renderer.element);
      place(props.clientRect);
    },
    onUpdate: (props: Suggestion) => {
      if (container) container.style.display = "";
      renderer?.updateProps(listProps(props));
      place(props.clientRect);
    },
    onKeyDown: (props: SuggestionKeyDownProps) => {
      if (props.event.key === "Escape") {
        // Dismiss the dropdown without closing an enclosing modal; it
        // reappears (via onUpdate) once the query changes again.
        if (container) container.style.display = "none";
        return true;
      }
      return renderer?.ref?.onKeyDown(props) ?? false;
    },
    onExit: destroy,
  };
};

/**
 * A plain-text Tiptap extension set: paragraphs of literal text (Markdown is
 * authored verbatim) plus atomic `@<toolName>` mention chips with a suggestion
 * dropdown. Built once per editor; live props arrive via {@link refs}.
 */
export const buildMentionExtensions = (
  refs: MentionExtensionRefs,
  maxLength?: number,
): Extensions => {
  const mention = Mention.extend({
    addNodeView() {
      return ReactNodeViewRenderer(createMentionNodeView(refs));
    },
  }).configure({
    renderText: ({ node }) => `@${node.attrs.label ?? node.attrs.id}`,
    suggestion: {
      char: "@",
      items: ({ query }): SuggestionItem[] => {
        const q = query.toLowerCase();
        const names = refs.toolNames.current;
        const pool = q
          ? names.filter((name) => name.toLowerCase().includes(q))
          : names;
        return pool.slice(0, MAX_SUGGESTIONS);
      },
      command: ({ editor, range, props }) => {
        editor
          .chain()
          .focus()
          .insertContentAt(range, [
            { type: "mention", attrs: props },
            { type: "text", text: " " },
          ])
          .run();
      },
      render: createSuggestionRenderer(refs),
    },
  });

  return [
    Document,
    Paragraph,
    Text,
    HardBreak,
    History,
    CharacterCount.configure({ limit: maxLength }),
    mention,
  ];
};
