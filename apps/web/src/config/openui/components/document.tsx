"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { ArrowDown01Icon, Copy01Icon, Tick01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import Underline from "@tiptap/extension-underline";
import { BubbleMenu, EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import React from "react";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const textDocumentSchema = z.object({
  title: z.string(),
  body: z.string(),
  fields: z
    .array(z.object({ label: z.string(), value: z.string() }))
    .optional(),
});

// ---------------------------------------------------------------------------
// HTML → Markdown converter (handles tiptap output)
// ---------------------------------------------------------------------------

function htmlToMarkdown(html: string): string {
  if (typeof window === "undefined") return html;
  const doc = new DOMParser().parseFromString(html, "text/html");

  function nodeToMd(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const el = node as Element;
    const tag = el.tagName.toLowerCase();
    const inner = Array.from(el.childNodes).map(nodeToMd).join("");

    switch (tag) {
      case "h1":
        return `# ${inner}\n\n`;
      case "h2":
        return `## ${inner}\n\n`;
      case "h3":
        return `### ${inner}\n\n`;
      case "p":
        return `${inner}\n\n`;
      case "strong":
      case "b":
        return `**${inner}**`;
      case "em":
      case "i":
        return `*${inner}*`;
      case "u":
        return `__${inner}__`;
      case "br":
        return "\n";
      case "ul":
        return `${inner}\n`;
      case "ol": {
        let index = 0;
        return (
          Array.from(el.children)
            .map((child) => {
              if (child.tagName.toLowerCase() === "li") {
                index += 1;
                return `${index}. ${Array.from(child.childNodes).map(nodeToMd).join("")}\n`;
              }
              return nodeToMd(child);
            })
            .join("") + "\n"
        );
      }
      case "li":
        return `- ${inner}\n`;
      case "body":
        return inner;
      default:
        return inner;
    }
  }

  return nodeToMd(doc.body)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// ---------------------------------------------------------------------------
// Toolbar button (used inside BubbleMenu)
// ---------------------------------------------------------------------------

interface ToolbarButtonProps {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function ToolbarButton({ active, onClick, children }: ToolbarButtonProps) {
  return (
    <Button
      variant="light"
      size="sm"
      onPress={() => onClick()}
      className={[
        "h-7 min-w-7 rounded px-1.5",
        "text-xs font-semibold transition-all duration-100",
        active
          ? "bg-zinc-600 text-zinc-100"
          : "text-zinc-400 hover:bg-zinc-500 hover:text-zinc-50",
      ].join(" ")}
    >
      {children}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

export function TextDocumentView(props: z.infer<typeof textDocumentSchema>) {
  const { title, fields, body } = props;
  const [copied, setCopied] = React.useState(false);

  const editor = useEditor({
    extensions: [StarterKit, Underline],
    content: body,
    editorProps: {
      attributes: {
        class:
          "outline-none text-sm text-zinc-200 leading-relaxed space-y-1 min-h-[120px]",
      },
    },
  });

  const flashCopied = () => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const copyAsMarkdown = React.useCallback(() => {
    const fieldLines = (fields ?? [])
      .map((f) => `**${f.label}:** ${f.value}`)
      .join("\n");
    const bodyMd = htmlToMarkdown(editor?.getHTML() ?? "");
    const full = [fieldLines, bodyMd].filter(Boolean).join("\n\n");
    void navigator.clipboard
      .writeText(full)
      .then(flashCopied)
      .catch(() => {});
  }, [fields, editor]);

  const copyAsText = React.useCallback(() => {
    const fieldLines = (fields ?? [])
      .map((f) => `${f.label}: ${f.value}`)
      .join("\n");
    const bodyText = editor?.getText() ?? "";
    const full = [fieldLines, bodyText].filter(Boolean).join("\n\n");
    void navigator.clipboard
      .writeText(full)
      .then(flashCopied)
      .catch(() => {});
  }, [fields, editor]);

  return (
    <div className="openui-document rounded-2xl bg-zinc-800 p-4 w-full max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-zinc-100">{title}</span>

        {/* Copy button group */}
        <div
          className={[
            "flex items-center rounded-lg overflow-hidden transition-all duration-150",
            copied ? "bg-emerald-500/20" : "bg-zinc-700/50",
          ].join(" ")}
        >
          {/* Main copy button — copies as markdown */}
          <Button
            isIconOnly
            variant="light"
            size="sm"
            onPress={copyAsMarkdown}
            aria-label={copied ? "Copied" : "Copy as Markdown"}
            className={copied ? "text-emerald-400" : "text-zinc-400"}
          >
            {copied ? <Tick01Icon size={14} /> : <Copy01Icon size={14} />}
          </Button>

          {/* Divider */}
          <div
            className={[
              "h-4 w-px",
              copied ? "bg-emerald-500/30" : "bg-zinc-600",
            ].join(" ")}
          />

          {/* Chevron dropdown trigger */}
          <Dropdown placement="bottom-end">
            <DropdownTrigger>
              <Button
                isIconOnly
                variant="light"
                size="sm"
                aria-label="Copy options"
                className={copied ? "text-emerald-400" : "text-zinc-400"}
              >
                <ArrowDown01Icon size={12} />
              </Button>
            </DropdownTrigger>
            <DropdownMenu
              aria-label="Copy options"
              onAction={(key) => {
                if (key === "markdown") copyAsMarkdown();
                if (key === "text") copyAsText();
              }}
            >
              <DropdownItem key="markdown">Copy as Markdown</DropdownItem>
              <DropdownItem key="text">Copy as Plain Text</DropdownItem>
            </DropdownMenu>
          </Dropdown>
        </div>
      </div>

      {/* Fields */}
      {fields && fields.length > 0 && (
        <div className="mb-3 space-y-1">
          {fields.map((field, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static LLM-provided field list
            <div key={i} className="flex gap-2 text-sm">
              <span className="min-w-16 shrink-0 font-medium text-zinc-400">
                {field.label}
              </span>
              <span className="text-zinc-200">{field.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Divider */}
      <div className="mb-3 h-px bg-zinc-700" />

      {/* Bubble menu — appears on text selection */}
      {editor && (
        <BubbleMenu
          editor={editor}
          tippyOptions={{ duration: 100 }}
          className="flex items-center gap-0.5 rounded-xl bg-zinc-700 p-1 shadow-lg"
        >
          <ToolbarButton
            active={editor.isActive("heading", { level: 1 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 1 }).run()
            }
          >
            H1
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("heading", { level: 2 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            H2
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("paragraph")}
            onClick={() => editor.chain().focus().setParagraph().run()}
          >
            P
          </ToolbarButton>
          <div className="mx-1 h-4 w-px bg-zinc-600" />
          <ToolbarButton
            active={editor.isActive("bold")}
            onClick={() => editor.chain().focus().toggleBold().run()}
          >
            <span className="font-bold">B</span>
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("italic")}
            onClick={() => editor.chain().focus().toggleItalic().run()}
          >
            <span className="italic">I</span>
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("underline")}
            onClick={() => editor.chain().focus().toggleUnderline().run()}
          >
            <span className="underline">U</span>
          </ToolbarButton>
        </BubbleMenu>
      )}

      {/* Editor */}
      <div className="[&_.ProseMirror_h1]:text-xl [&_.ProseMirror_h1]:font-semibold [&_.ProseMirror_h1]:text-zinc-100 [&_.ProseMirror_h1]:mb-2 [&_.ProseMirror_h2]:text-base [&_.ProseMirror_h2]:font-semibold [&_.ProseMirror_h2]:text-zinc-100 [&_.ProseMirror_h2]:mb-1.5 [&_.ProseMirror_p]:text-sm [&_.ProseMirror_p]:text-zinc-200 [&_.ProseMirror_p]:leading-relaxed [&_.ProseMirror_p+p]:mt-2">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// defineComponent registration
// ---------------------------------------------------------------------------

export const textDocumentDef = defineComponent({
  name: "TextDocument",
  description:
    "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
  props: textDocumentSchema,
  component: ({ props }) => React.createElement(TextDocumentView, props),
});
