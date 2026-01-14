import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import { User } from "@heroui/user";
import CharacterCount from "@tiptap/extension-character-count";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Typography from "@tiptap/extension-typography";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import he from "he";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Drawer } from "vaul";

import Spinner from "@/components/ui/spinner";
import GmailBody from "@/features/mail/components/GmailBody";
import { useEmailSummary } from "@/features/mail/hooks/useEmailAnalysis";
import { parseEmail } from "@/features/mail/utils/mailUtils";
import {
  ArrowLeftDoubleIcon,
  ArrowTurnBackwardIcon,
  Cancel01Icon,
  MagicWand05Icon,
  SentIcon,
  StarsIcon,
} from "@/icons";
// import { MenuBar } from "@/features/notes/components/NotesMenuBar";
import type {
  EmailData,
  EmailImportanceSummary,
} from "@/types/features/mailTypes";

import { useFetchEmailById } from "../hooks/useFetchEmailById";

interface ViewEmailProps {
  mailId: string | null;
  onOpenChange: () => void;
  threadMessages?: EmailData[];
  isLoadingThread?: boolean;
}

function AISummary({
  analysis,
  isLoading,
}: {
  analysis: EmailImportanceSummary | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="mb-3 flex w-fit flex-col rounded-xl bg-surface-200 p-2 shadow-md outline outline-zinc-700">
        <div className="relative flex items-center gap-3 text-sm font-medium text-white">
          <Chip
            classNames={{
              content:
                "text-sm relative flex! flex-row text-primary items-center gap-1 pl-3 font-medium",
            }}
            variant="flat"
            color="primary"
          >
            <StarsIcon width={17} height={17} fill={"#00bbff"} />
            <span>Loading AI Analysis...</span>
          </Chip>
        </div>
        <div className="p-2">
          <Spinner />
        </div>
      </div>
    );
  }

  if (!analysis) return null;

  return (
    <div className="mb-3 flex w-fit flex-col rounded-xl bg-surface-200 p-2 shadow-md outline outline-zinc-700">
      <div className="relative flex items-center gap-3 text-sm font-medium text-white">
        <Chip
          classNames={{
            content:
              "text-sm relative flex! flex-row text-primary items-center gap-1 pl-3 font-medium",
          }}
          variant="flat"
          color="primary"
        >
          <StarsIcon width={17} height={17} fill={"#00bbff"} />
          <span>GAIA AI Analysis</span>
        </Chip>
      </div>

      {/* Summary */}
      <div className="p-2 text-sm text-white">
        <strong>Summary:</strong> {analysis.summary}
      </div>

      {/* Importance and Category */}
      <div className="flex flex-wrap gap-2 px-2 pb-2">
        <Chip
          size="sm"
          variant="flat"
          color={
            analysis.importance_level === "URGENT"
              ? "danger"
              : analysis.importance_level === "HIGH"
                ? "warning"
                : analysis.importance_level === "MEDIUM"
                  ? "primary"
                  : "default"
          }
        >
          {analysis.importance_level}
        </Chip>

        {analysis.category && (
          <Chip size="sm" variant="flat" color="secondary">
            {analysis.category}
          </Chip>
        )}

        {analysis.intent && (
          <Chip size="sm" variant="flat" color="secondary">
            {analysis.intent}
          </Chip>
        )}
      </div>

      {/* Semantic Labels */}
      {analysis.semantic_labels && analysis.semantic_labels.length > 0 && (
        <div className="px-2 pb-2">
          <Accordion variant="light" selectionMode="multiple" className="px-0">
            <AccordionItem
              key="labels"
              aria-label="Semantic Labels"
              title={
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">Labels</span>
                  <Chip size="sm" variant="flat" color="default">
                    {analysis.semantic_labels.length}
                  </Chip>
                </div>
              }
              className="px-0"
            >
              <div className="flex flex-wrap gap-1 pb-2">
                {analysis.semantic_labels.map((label) => (
                  <Chip
                    key={label}
                    size="sm"
                    variant="bordered"
                    color="primary"
                  >
                    {label}
                  </Chip>
                ))}
              </div>
            </AccordionItem>
          </Accordion>
        </div>
      )}
    </div>
  );
}

export default function ViewEmail({
  mailId,
  onOpenChange,
  threadMessages = [],
  isLoadingThread = false,
}: ViewEmailProps) {
  const { mail } = useFetchEmailById(mailId);

  const { name: nameFrom, email: emailFrom } = parseEmail(mail?.from || "");
  const [showReplyEditor, setShowReplyEditor] = useState(false);
  const [replyTo, setReplyTo] = useState<EmailData | null>(null);
  const [isSending, setIsSending] = useState(false);

  // Only fetch individually if not in cache
  const {
    data: aiAnalysisData,
    isLoading: isLoadingAnalysis,
    error: analysisError,
  } = useEmailSummary(mailId || "", !!mailId);

  const aiAnalysis = aiAnalysisData?.email || null;

  const sortedThreadMessages = [...threadMessages].sort((a, b) => {
    return new Date(a.time).getTime() - new Date(b.time).getTime();
  });

  // const getRecipients = (email: EmailData | null) => {
  //   if (!email) return { to: "", cc: "", bcc: "" };

  //   const headers = email.headers || {};
  //   return {
  //     to: headers["Reply-To"] || headers["From"] || email.from || "",
  //     cc: "",
  //     bcc: "",
  //   };
  // };

  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link,
      Typography,
      Placeholder.configure({
        placeholder: "Write your reply here...",
      }),
      CharacterCount.configure({
        limit: 10000,
      }),
    ],
    content: `<p></p>`,
  });

  // Reset editor content when opening/closing the reply form
  useEffect(() => {
    if (editor && showReplyEditor) {
      editor.commands.setContent("<p></p>");
      editor.commands.focus("end");
    }
  }, [editor, showReplyEditor]);

  const handleReply = (email: EmailData) => {
    setReplyTo(email);
    setShowReplyEditor(true);
  };

  const handleSendReply = async () => {
    if (!editor || !replyTo || !replyTo.id) return;

    const content = editor.getHTML();
    if (!content || content === "<p></p>") {
      toast.error("Please write a reply before sending");
      return;
    }

    setIsSending(true);
    try {
      const recipient = parseEmail(replyTo.from).email;
      if (!recipient) {
        toast.error("Invalid recipient email address");
        return;
      }

      if (!replyTo.threadId) {
        toast.error("Cannot reply: Thread ID is missing");
        return;
      }

      // TODO: Backend reply endpoint doesn't exist yet
      // await mailApi.replyToEmail({
      //   threadId: replyTo.threadId,
      //   to: [recipient],
      //   subject: `Re: ${replyTo.subject || ""}`,
      //   body: content,
      // });

      toast.error("ArrowTurnBackwardIcon functionality is not yet implemented");
      setShowReplyEditor(false);
      editor.commands.setContent("<p></p>");
    } catch (error) {
      console.error("Error sending reply:", error);
      toast.error("Failed to send reply. Please try again.");
    } finally {
      setIsSending(false);
    }
  };

  const handleCancelReply = () => {
    setShowReplyEditor(false);
    setReplyTo(null);
    if (editor) {
      editor.commands.setContent("<p></p>");
    }
  };

  const handleAnalyzeEmail = async () => {
    if (!mailId) return;

    // If we already have analysis, no need to fetch again
    if (aiAnalysis) {
      toast.success("Email analysis already available");
      return;
    }

    try {
      // The analysis should be automatically triggered when email is processed
      // For now, we'll just show a message
      toast.info("Email analysis is processed automatically in the background");
    } catch (error) {
      console.error("Error analyzing email:", error);
      toast.error("Failed to analyze email. Please try again.");
    }
  };

  return (
    <Drawer.Root direction="right" open={!!mailId} onOpenChange={onOpenChange}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-md" />
        <Drawer.Content
          className="fixed top-2 right-0 bottom-2 z-10 flex w-screen outline-hidden sm:w-[50vw]"
          style={
            { "--initial-transform": "calc(100% + 8px)" } as React.CSSProperties
          }
        >
          <div className="relative flex h-full w-full grow flex-col overflow-y-auto rounded-l-2xl bg-surface-100 p-6 pt-4">
            <div className="mb-2 flex w-full justify-end">
              <Tooltip content="Close" color="foreground">
                <div className="cursor-pointer">
                  <Cancel01Icon width={18} onClick={onOpenChange} />
                </div>
              </Tooltip>
            </div>
            <header className="mb-2 flex items-center gap-2">
              <Button
                color="primary"
                className="font-medium"
                startContent={<MagicWand05Icon />}
                isLoading={isLoadingAnalysis}
                onPress={handleAnalyzeEmail}
                isDisabled={isLoadingAnalysis}
              >
                {isLoadingAnalysis
                  ? "Loading..."
                  : aiAnalysis
                    ? "AI Analysis"
                    : "Get AI Analysis"}
              </Button>

              <div className="ml-auto flex gap-2">
                <Button
                  color="primary"
                  variant="flat"
                  startContent={<ArrowTurnBackwardIcon size={16} />}
                  onPress={() => mail && handleReply(mail)}
                >
                  ArrowTurnBackwardIcon
                </Button>
                <Button
                  color="primary"
                  variant="flat"
                  startContent={<ArrowLeftDoubleIcon size={16} />}
                  onPress={() => mail && handleReply(mail)}
                >
                  ArrowTurnBackwardIcon All
                </Button>
              </div>
            </header>

            <AISummary analysis={aiAnalysis} isLoading={isLoadingAnalysis} />

            {analysisError && (
              <div className="mb-3 flex w-fit flex-col rounded-xl bg-red-900/20 p-2 shadow-md outline outline-red-700">
                <div className="p-2 text-sm text-red-300">
                  Failed to load AI analysis. The email may not have been
                  processed yet.
                </div>
              </div>
            )}

            {mail?.subject && (
              <Drawer.Title className="font-medium text-foreground">
                {mail?.subject}
              </Drawer.Title>
            )}

            <Drawer.Description className="space-y-4 text-foreground-600">
              {isLoadingThread && (
                <div className="flex items-center justify-center py-4">
                  <Spinner />
                  <span className="ml-2">Loading conversation...</span>
                </div>
              )}

              {/* Thread messages */}
              {sortedThreadMessages.length > 0 ? (
                <div className="mt-4 space-y-6">
                  {sortedThreadMessages.map((message) => {
                    const {
                      name: messageSenderName,
                      email: messageSenderEmail,
                    } = parseEmail(message.from);
                    const isCurrentEmail = mailId === message.id;

                    return (
                      <div
                        key={message.id}
                        className={`rounded-lg p-4 ${isCurrentEmail ? "bg-surface-200" : "bg-surface-100"} border-l-2 ${isCurrentEmail ? "border-primary" : "border-border-surface-700"}`}
                      >
                        <div className="mb-2 flex items-start justify-between">
                          <User
                            avatarProps={{
                              src: "/images/avatars/default.webp",
                              size: "sm",
                            }}
                            description={messageSenderEmail}
                            name={messageSenderName}
                            classNames={{
                              name: "font-medium",
                              description: "text-gray-400",
                            }}
                          />
                          <div className="text-xs text-gray-400">
                            {new Date(message.time).toLocaleString()}
                          </div>
                        </div>

                        {message.snippet && (
                          <div className="text-muted-foreground mb-2 text-sm">
                            {he.decode(message.snippet)}
                          </div>
                        )}

                        <div className="mt-2">
                          <GmailBody email={message} />
                        </div>

                        <div className="mt-4 flex justify-end">
                          <Button
                            size="sm"
                            color="primary"
                            variant="flat"
                            startContent={<ArrowTurnBackwardIcon size={14} />}
                            onPress={() => handleReply(message)}
                          >
                            ArrowTurnBackwardIcon
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : mail ? (
                <>
                  {mail?.snippet && (
                    <div className="text-md text-muted-foreground">
                      {he.decode(mail.snippet)}
                    </div>
                  )}
                  <User
                    avatarProps={{
                      src: "/images/avatars/default.webp",
                      size: "sm",
                    }}
                    description={emailFrom}
                    name={nameFrom}
                    classNames={{
                      name: "font-medium",
                      description: "text-gray-400",
                    }}
                  />
                  <div>
                    <hr className="my-4 border-gray-700" />
                    <GmailBody email={mail} />
                  </div>
                </>
              ) : null}

              {/* ArrowTurnBackwardIcon editor */}
              {showReplyEditor && replyTo && (
                <div className="mt-4 border-t-2 border-border-surface-700 pt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm">
                      <span className="font-medium">
                        ArrowTurnBackwardIcon to:{" "}
                      </span>
                      <span className="text-gray-400">
                        {parseEmail(replyTo.from).name ||
                          parseEmail(replyTo.from).email}
                      </span>
                    </div>
                    <Button
                      size="sm"
                      color="danger"
                      variant="light"
                      isIconOnly
                      onPress={handleCancelReply}
                    >
                      <Cancel01Icon size={16} />
                    </Button>
                  </div>

                  <div className="rounded-lg border border-border-surface-700 bg-surface-200">
                    {/* <MenuBar editor={editor} /> */}
                    <div className="max-h-[250px] min-h-[150px] overflow-y-auto px-4 py-2">
                      <EditorContent editor={editor} />
                    </div>
                  </div>

                  <div className="mt-2 flex justify-end">
                    <Button
                      color="primary"
                      startContent={<SentIcon size={16} />}
                      onPress={handleSendReply}
                      isLoading={isSending}
                      isDisabled={isSending}
                    >
                      {isSending ? "Sending..." : "SentIcon Reply"}
                    </Button>
                  </div>
                </div>
              )}
            </Drawer.Description>
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
