"use client";
import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import CharacterCount from "@tiptap/extension-character-count";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Typography from "@tiptap/extension-typography";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useCallback, useEffect } from "react";

import { parseEmail } from "@/features/mail/utils/mailUtils";
import { Cancel01Icon, SentIcon } from "@/icons";
import type { EmailData } from "@/types/features/mailTypes";

interface ReplyEditorProps {
  replyTo: EmailData;
  onSend: (htmlContent: string) => Promise<void>;
  onCancel: () => void;
  isSending: boolean;
  initialContent?: string;
}

export function ReplyEditor({
  replyTo,
  onSend,
  onCancel,
  isSending,
  initialContent,
}: ReplyEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link,
      Typography,
      Placeholder.configure({
        placeholder: "Write your reply here...",
      }),
      CharacterCount.configure({ limit: 10000 }),
    ],
    content: initialContent || "<p></p>",
  });

  useEffect(() => {
    if (editor && initialContent) {
      editor.commands.setContent(initialContent);
      editor.commands.focus("end");
    }
  }, [editor, initialContent]);

  const hasContent = useCallback(() => {
    if (!editor) return false;
    return editor.getText().trim().length > 0;
  }, [editor]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (hasContent()) {
        e.preventDefault();
      }
    };

    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("beforeunload", handler);
    };
  }, [hasContent]);

  const handleSend = async () => {
    if (!editor) return;
    const content = editor.getHTML();
    const textContent = editor.getText().trim();
    if (!content || !textContent) return;
    await onSend(content);
  };

  const recipientDisplay =
    parseEmail(replyTo.from).name || parseEmail(replyTo.from).email;

  return (
    <div className="mt-4 border-t-2 border-zinc-700 pt-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm">
          <span className="font-medium">Reply to: </span>
          <span className="text-gray-400">{recipientDisplay}</span>
        </div>
        <Button
          size="sm"
          color="danger"
          variant="light"
          isIconOnly
          onPress={onCancel}
        >
          <Cancel01Icon size={16} />
        </Button>
      </div>

      <div className="rounded-lg border border-zinc-700 bg-zinc-800">
        {editor && (
          <div className="flex items-center gap-1 border-b border-zinc-700 px-2 py-1">
            <Tooltip content="Bold" delay={400}>
              <button
                type="button"
                className={`rounded px-2 py-1 text-sm font-bold transition-colors ${
                  editor.isActive("bold")
                    ? "bg-primary text-white"
                    : "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleBold().run();
                }}
              >
                B
              </button>
            </Tooltip>
            <Tooltip content="Italic" delay={400}>
              <button
                type="button"
                className={`rounded px-2 py-1 text-sm italic transition-colors ${
                  editor.isActive("italic")
                    ? "bg-primary text-white"
                    : "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleItalic().run();
                }}
              >
                I
              </button>
            </Tooltip>
            <Tooltip content="Underline" delay={400}>
              <button
                type="button"
                className={`rounded px-2 py-1 text-sm underline transition-colors ${
                  editor.isActive("underline")
                    ? "bg-primary text-white"
                    : "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor.chain().focus().toggleUnderline().run();
                }}
              >
                U
              </button>
            </Tooltip>
            <div className="mx-1 h-4 w-px bg-zinc-600" />
            <Tooltip content="Bullet List" delay={400}>
              <button
                type="button"
                className={`rounded px-2 py-1 text-sm transition-colors ${
                  editor.isActive("bulletList")
                    ? "bg-primary text-white"
                    : "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor
                    .chain()
                    .focus()
                    .toggleBulletList()
                    .run();
                }}
              >
                &bull;
              </button>
            </Tooltip>
            <Tooltip content="Ordered List" delay={400}>
              <button
                type="button"
                className={`rounded px-2 py-1 text-sm transition-colors ${
                  editor.isActive("orderedList")
                    ? "bg-primary text-white"
                    : "text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  editor
                    .chain()
                    .focus()
                    .toggleOrderedList()
                    .run();
                }}
              >
                1.
              </button>
            </Tooltip>
          </div>
        )}
        <div className="max-h-[250px] min-h-[150px] overflow-y-auto px-4 py-2">
          <EditorContent editor={editor} />
        </div>
      </div>

      <div className="mt-2 flex justify-end">
        <Button
          color="primary"
          startContent={<SentIcon size={16} />}
          onPress={handleSend}
          isLoading={isSending}
          isDisabled={isSending}
        >
          {isSending ? "Sending..." : "Send Reply"}
        </Button>
      </div>
    </div>
  );
}
