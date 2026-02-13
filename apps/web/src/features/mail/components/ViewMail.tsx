"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import { User } from "@heroui/user";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import Spinner from "@/components/ui/spinner";
import { mailApi } from "@/features/mail/api/mailApi";
import GmailBody from "@/features/mail/components/GmailBody";
import { ReplyEditor } from "@/features/mail/components/ReplyEditor";
import { SmartReplyChips } from "@/features/mail/components/SmartReplyChips";
import { useEmailSummary } from "@/features/mail/hooks/useEmailAnalysis";
import { parseEmail } from "@/features/mail/utils/mailUtils";
import {
  ArrowLeftDoubleIcon,
  ArrowTurnBackwardIcon,
  Cancel01Icon,
  MagicWand05Icon,
  StarsIcon,
} from "@/icons";
import type {
  EmailData,
  EmailImportanceSummary,
  SmartReply,
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
      <div className="mb-3 flex w-fit flex-col rounded-xl bg-zinc-800 p-2 shadow-md outline outline-zinc-700">
        <div className="relative flex items-center gap-3 text-sm font-medium text-white">
          <Chip
            classNames={{
              content:
                "text-sm relative flex! flex-row text-primary items-center gap-1 pl-3 font-medium",
            }}
            variant="flat"
            color="primary"
          >
            <StarsIcon width={17} height={17} fill="#00bbff" />
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
    <div className="mb-3 flex w-fit flex-col rounded-xl bg-zinc-800 p-2 shadow-md outline outline-zinc-700">
      <div className="relative flex items-center gap-3 text-sm font-medium text-white">
        <Chip
          classNames={{
            content:
              "text-sm relative flex! flex-row text-primary items-center gap-1 pl-3 font-medium",
          }}
          variant="flat"
          color="primary"
        >
          <StarsIcon width={17} height={17} fill="#00bbff" />
          <span>GAIA AI Analysis</span>
        </Chip>
      </div>

      <div className="p-2 text-sm text-white">
        <strong>Summary:</strong> {analysis.summary}
      </div>

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

const springTransition = {
  type: "spring" as const,
  stiffness: 300,
  damping: 30,
  mass: 0.8,
};

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
  const [replyInitialContent, setReplyInitialContent] = useState<
    string | undefined
  >(undefined);

  const { data: aiAnalysisData, isLoading: isLoadingAnalysis } =
    useEmailSummary(mailId || "", !!mailId);

  const aiAnalysis = aiAnalysisData?.email || null;

  const sortedThreadMessages = [...threadMessages].sort(
    (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
  );

  const handleReply = (email: EmailData) => {
    setReplyTo(email);
    setReplyInitialContent(undefined);
    setShowReplyEditor(true);
  };

  const handleSmartReplySelect = (reply: SmartReply) => {
    if (mail) {
      setReplyTo(mail);
      setReplyInitialContent(reply.body);
      setShowReplyEditor(true);
    }
  };

  const handleSendReply = async (htmlContent: string) => {
    if (!replyTo) return;

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

      await mailApi.replyToEmail({
        to: recipient,
        subject: `Re: ${replyTo.subject || ""}`,
        body: htmlContent,
        threadId: replyTo.threadId,
      });

      setShowReplyEditor(false);
      setReplyTo(null);
      setReplyInitialContent(undefined);
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
    setReplyInitialContent(undefined);
  };

  const handleAnalyzeEmail = async () => {
    if (!mailId) return;
    if (aiAnalysis) {
      toast.success("Email analysis already available");
      return;
    }

    try {
      await mailApi.analyzeEmail(mailId);
      toast.success("Email analysis started");
    } catch (error) {
      console.error("Error analyzing email:", error);
      toast.error("Failed to analyze email. Please try again.");
    }
  };

  const handleEscapeKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape" && mailId) {
        onOpenChange();
      }
    },
    [mailId, onOpenChange],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleEscapeKey);
    return () => document.removeEventListener("keydown", handleEscapeKey);
  }, [handleEscapeKey]);

  return (
    <AnimatePresence>
      {!!mailId && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-md"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onOpenChange}
          />
          <motion.div
            className="fixed top-2 right-0 bottom-2 z-50 flex w-screen outline-hidden sm:w-[50vw]"
            initial={{ x: "100%", scale: 0.95 }}
            animate={{ x: 0, scale: 1 }}
            exit={{ x: "100%", scale: 0.95 }}
            transition={springTransition}
          >
            <div className="relative flex h-full w-full grow flex-col overflow-y-auto rounded-l-2xl bg-zinc-900 p-6 pt-4">
              <div className="mb-2 flex w-full justify-end">
                <Tooltip content="Close" color="foreground">
                  <div className="cursor-pointer">
                    <Cancel01Icon width={18} onClick={onOpenChange} />
                  </div>
                </Tooltip>
              </div>

              <header className="mb-2 flex items-center gap-2">
                {!aiAnalysis && (
                  <Button
                    color="primary"
                    className="font-medium"
                    startContent={<MagicWand05Icon />}
                    isLoading={isLoadingAnalysis}
                    onPress={handleAnalyzeEmail}
                    isDisabled={isLoadingAnalysis}
                  >
                    Get AI Analysis
                  </Button>
                )}

                <div className="ml-auto flex gap-2">
                  <Button
                    color="primary"
                    variant="flat"
                    startContent={<ArrowTurnBackwardIcon size={16} />}
                    onPress={() => mail && handleReply(mail)}
                  >
                    Reply
                  </Button>
                  <Button
                    color="primary"
                    variant="flat"
                    startContent={<ArrowLeftDoubleIcon size={16} />}
                    onPress={() => mail && handleReply(mail)}
                  >
                    Reply All
                  </Button>
                </div>
              </header>

              <AISummary analysis={aiAnalysis} isLoading={isLoadingAnalysis} />

              {mail?.subject && (
                <h2 className="font-medium text-foreground">{mail.subject}</h2>
              )}

              <div className="space-y-4 text-foreground-600">
                {isLoadingThread && (
                  <div className="flex items-center justify-center py-4">
                    <Spinner />
                    <span className="ml-2">Loading conversation...</span>
                  </div>
                )}

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
                          className={`rounded-lg p-4 ${isCurrentEmail ? "bg-zinc-800" : "bg-zinc-900"} border-l-2 ${isCurrentEmail ? "border-primary" : "border-zinc-700"}`}
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
                              Reply
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : mail ? (
                  <>
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

                {mailId && !showReplyEditor && (
                  <SmartReplyChips
                    messageId={mailId}
                    onSelectReply={handleSmartReplySelect}
                  />
                )}

                {showReplyEditor && replyTo && (
                  <ReplyEditor
                    replyTo={replyTo}
                    onSend={handleSendReply}
                    onCancel={handleCancelReply}
                    isSending={isSending}
                    initialContent={replyInitialContent}
                  />
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
