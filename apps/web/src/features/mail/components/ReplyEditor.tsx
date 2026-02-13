"use client";
import { Button } from "@heroui/button";
import CharacterCount from "@tiptap/extension-character-count";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Typography from "@tiptap/extension-typography";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

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

  const handleSend = async () => {
    if (!editor) return;
    const content = editor.getHTML();
    if (!content || content === "<p></p>") return;
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
