"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Spinner as HeroSpinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { User } from "@heroui/user";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import Spinner from "@/components/ui/spinner";
import { useUser } from "@/features/auth/hooks/useUser";
import { mailApi } from "@/features/mail/api/mailApi";
import { EmailAttachments } from "@/features/mail/components/EmailAttachments";
import GmailBody from "@/features/mail/components/GmailBody";
import { ReplyEditor } from "@/features/mail/components/ReplyEditor";
import { SmartReplyChips } from "@/features/mail/components/SmartReplyChips";
import { useEmailSummary } from "@/features/mail/hooks/useEmailAnalysis";
import { parseEmail } from "@/features/mail/utils/mailUtils";
import {
  ArrowLeftDoubleIcon,
  ArrowTurnBackwardIcon,
  Cancel01Icon,
  ChevronDown,
  ChevronUp,
  MagicWand05Icon,
  Share08Icon,
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
            <StarsIcon
              width={17}
              height={17}
              className="text-primary"
              fill="currentColor"
            />
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
          <StarsIcon
            width={17}
            height={17}
            className="text-primary"
            fill="currentColor"
          />
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
      </div>

      {analysis.semantic_labels && analysis.semantic_labels.length > 0 && (
        <div className="px-2 pb-2">
          <Accordion
            variant="light"
            selectionMode="multiple"
            className="px-0"
          >
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

type ReplyMode = "reply" | "replyAll" | "forward";

export default function ViewEmail({
  mailId,
  onOpenChange,
  threadMessages = [],
  isLoadingThread = false,
}: ViewEmailProps) {
  const { mail, isLoading } = useFetchEmailById(mailId);
  const { email: currentUserEmail } = useUser();
  const { name: nameFrom, email: emailFrom } = parseEmail(
    mail?.from || "",
  );
  const [showReplyEditor, setShowReplyEditor] = useState(false);
  const [replyTo, setReplyTo] = useState<EmailData | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [replyInitialContent, setReplyInitialContent] = useState<
    string | undefined
  >(undefined);
  const [replyMode, setReplyMode] = useState<ReplyMode>("reply");
  const [forwardTo, setForwardTo] = useState("");
  const [expandedMessages, setExpandedMessages] = useState<
    Set<string>
  >(new Set());

  const modalContentRef = useRef<HTMLDivElement>(null);

  const { data: aiAnalysisData, isLoading: isLoadingAnalysis } =
    useEmailSummary(mailId || "", !!mailId);

  const aiAnalysis = aiAnalysisData?.email || null;

  // Task 10: Memoize sorted thread messages
  const sortedThreadMessages = useMemo(
    () =>
      [...threadMessages].sort(
        (a, b) =>
          new Date(a.time).getTime() - new Date(b.time).getTime(),
      ),
    [threadMessages],
  );

  // Task 12: Filter out current email from thread to avoid duplicate
  const filteredThreadMessages = useMemo(() => {
    if (sortedThreadMessages.length > 1) {
      return sortedThreadMessages.filter(
        (message) => message.id !== mailId,
      );
    }
    return sortedThreadMessages;
  }, [sortedThreadMessages, mailId]);

  // Task 19: Initialize expanded state - only latest message expanded
  useEffect(() => {
    if (filteredThreadMessages.length > 0) {
      const lastMessage =
        filteredThreadMessages[filteredThreadMessages.length - 1];
      setExpandedMessages(new Set([lastMessage.id]));
    }
  }, [filteredThreadMessages]);

  // Task 11: Reset reply state when mailId changes
  useEffect(() => {
    setShowReplyEditor(false);
    setReplyTo(null);
    setReplyInitialContent(undefined);
    setReplyMode("reply");
    setForwardTo("");
  }, [mailId]);

  // Task 36: Focus modal content when modal opens
  useEffect(() => {
    if (mailId && modalContentRef.current) {
      modalContentRef.current.focus();
    }
  }, [mailId]);

  const handleReply = (email: EmailData) => {
    setReplyTo(email);
    setReplyInitialContent(undefined);
    setReplyMode("reply");
    setShowReplyEditor(true);
  };

  // Task 1: Separate handler for Reply All
  const handleReplyAll = (email: EmailData) => {
    setReplyTo(email);
    setReplyInitialContent(undefined);
    setReplyMode("replyAll");
    setShowReplyEditor(true);
  };

  // Task 7: Forward handler
  const handleForward = (email: EmailData) => {
    const forwardContent = [
      "<br/><br/>",
      "---------- Forwarded message ----------",
      `<br/><strong>From:</strong> ${email.from}`,
      `<br/><strong>Subject:</strong> ${email.subject || "(no subject)"}`,
      `<br/><strong>Date:</strong> ${new Date(email.time).toLocaleString()}`,
      "<br/><br/>",
      email.body || email.snippet || "",
    ].join("");

    setReplyTo(email);
    setReplyInitialContent(forwardContent);
    setReplyMode("forward");
    setShowReplyEditor(true);
  };

  const handleSmartReplySelect = (reply: SmartReply) => {
    if (mail) {
      setReplyTo(mail);
      setReplyInitialContent(reply.body);
      setReplyMode("reply");
      setShowReplyEditor(true);
    }
  };

  // Task 19: Toggle expand/collapse of thread messages
  const toggleMessageExpanded = (messageId: string) => {
    setExpandedMessages((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
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

      if (replyMode === "forward") {
        // Task 51: Forward uses forwardTo recipient
        if (!forwardTo.trim()) {
          toast.error("Please enter a recipient email address");
          return;
        }

        const formData = new FormData();
        formData.append("to", forwardTo.trim());
        formData.append(
          "subject",
          `Fwd: ${replyTo.subject || ""}`,
        );
        formData.append("body", htmlContent);
        formData.append("is_html", "true");

        await mailApi.sendEmail(formData);
      } else if (replyMode === "replyAll") {
        // Reply All: include To and CC from original headers
        if (!replyTo.threadId) {
          toast.error("Cannot reply: Thread ID is missing");
          return;
        }

        const toHeader = replyTo.headers?.To || replyTo.headers?.to || "";
        const ccHeader = replyTo.headers?.Cc || replyTo.headers?.cc || "";

        // Collect all recipients: original sender + To + CC
        const allRecipients = [
          recipient,
          ...toHeader
            .split(",")
            .map((e: string) => parseEmail(e.trim()).email)
            .filter(Boolean),
        ];

        // Task 73: Exclude current user from Reply All recipients
        const filteredRecipients = currentUserEmail
          ? allRecipients.filter(
              (email) =>
                email.toLowerCase() !==
                currentUserEmail.toLowerCase(),
            )
          : allRecipients;
        const uniqueTo = [...new Set(filteredRecipients)].join(",");

        // Task 73: Also filter current user from CC
        const filteredCc = currentUserEmail
          ? ccHeader
              .split(",")
              .map((e: string) => e.trim())
              .filter((e: string) => {
                const parsed = parseEmail(e).email;
                return (
                  parsed &&
                  parsed.toLowerCase() !==
                    currentUserEmail.toLowerCase()
                );
              })
              .join(",")
          : ccHeader;

        const formData = new FormData();
        formData.append("to", uniqueTo);
        formData.append(
          "subject",
          `Re: ${replyTo.subject || ""}`,
        );
        formData.append("body", htmlContent);
        formData.append("thread_id", replyTo.threadId);
        formData.append("is_html", "true");
        if (filteredCc) {
          formData.append("cc", filteredCc);
        }

        await mailApi.sendEmail(formData);
      } else {
        // Standard reply
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
      }

      // Task 27: Success toast for reply send
      toast.success("Reply sent successfully");

      setShowReplyEditor(false);
      setReplyTo(null);
      setReplyInitialContent(undefined);
      setForwardTo("");
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
    setForwardTo("");
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
        // Task 26: Prevent close during reply editing
        if (showReplyEditor) {
          return;
        }
        onOpenChange();
      }
    },
    [mailId, onOpenChange, showReplyEditor],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleEscapeKey);
    return () =>
      document.removeEventListener("keydown", handleEscapeKey);
  }, [handleEscapeKey]);

  // Task 26: Handle backdrop click - prevent close during reply
  const handleBackdropClick = useCallback(() => {
    if (showReplyEditor) {
      return;
    }
    onOpenChange();
  }, [showReplyEditor, onOpenChange]);

  return (
    <AnimatePresence>
      {!!mailId && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-md"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={handleBackdropClick}
          />
          <motion.div
            className="fixed top-2 right-0 bottom-2 z-50 flex w-screen outline-hidden sm:w-[50vw]"
            initial={{ x: "100%", scale: 0.95 }}
            animate={{ x: 0, scale: 1 }}
            exit={{ x: "100%", scale: 0.95 }}
            transition={springTransition}
          >
            {/* Task 36: Focus management ref */}
            <div
              ref={modalContentRef}
              tabIndex={-1}
              className="relative flex h-full w-full grow flex-col overflow-y-auto rounded-l-2xl bg-zinc-900 p-6 pt-4 outline-none"
            >
              <div className="mb-2 flex w-full justify-end">
                <Tooltip content="Close" color="foreground">
                  <div className="cursor-pointer">
                    <Cancel01Icon
                      width={18}
                      onClick={onOpenChange}
                    />
                  </div>
                </Tooltip>
              </div>

              {/* Task 74: Loading state */}
              {isLoading && !mail && (
                <div className="flex flex-1 items-center justify-center">
                  <HeroSpinner size="lg" color="primary" />
                </div>
              )}

              {(!isLoading || mail) && (
              <>
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
                    startContent={
                      <ArrowTurnBackwardIcon size={16} />
                    }
                    onPress={() => mail && handleReply(mail)}
                  >
                    Reply
                  </Button>
                  {/* Task 1: Reply All with separate handler */}
                  <Button
                    color="primary"
                    variant="flat"
                    startContent={
                      <ArrowLeftDoubleIcon size={16} />
                    }
                    onPress={() =>
                      mail && handleReplyAll(mail)
                    }
                  >
                    Reply All
                  </Button>
                  {/* Task 7: Forward button */}
                  <Button
                    color="primary"
                    variant="flat"
                    startContent={<Share08Icon size={16} />}
                    onPress={() =>
                      mail && handleForward(mail)
                    }
                  >
                    Forward
                  </Button>
                </div>
              </header>

              <AISummary
                analysis={aiAnalysis}
                isLoading={isLoadingAnalysis}
              />

              {mail?.subject && (
                <h2 className="font-medium text-foreground">
                  {mail.subject}
                </h2>
              )}

              <div className="space-y-4 text-foreground-600">
                {isLoadingThread && (
                  <div className="flex items-center justify-center py-4">
                    <Spinner />
                    <span className="ml-2">
                      Loading conversation...
                    </span>
                  </div>
                )}

                {filteredThreadMessages.length > 0 ? (
                  <div className="mt-4 space-y-6">
                    {filteredThreadMessages.map((message) => {
                      const {
                        name: messageSenderName,
                        email: messageSenderEmail,
                      } = parseEmail(message.from);
                      const isExpanded = expandedMessages.has(
                        message.id,
                      );

                      return (
                        <div
                          key={message.id}
                          className="rounded-lg border-l-2 border-zinc-700 bg-zinc-900 p-4"
                        >
                          {/* Task 19: Clickable header to toggle collapse */}
                          <div
                            className="mb-2 flex cursor-pointer items-start justify-between"
                            onClick={() =>
                              toggleMessageExpanded(
                                message.id,
                              )
                            }
                            onKeyDown={(e) => {
                              if (
                                e.key === "Enter" ||
                                e.key === " "
                              ) {
                                toggleMessageExpanded(
                                  message.id,
                                );
                              }
                            }}
                            role="button"
                            tabIndex={0}
                          >
                            <User
                              avatarProps={{
                                src: "/images/avatars/default.webp",
                                size: "sm",
                              }}
                              description={
                                messageSenderEmail
                              }
                              name={messageSenderName}
                              classNames={{
                                name: "font-medium",
                                description:
                                  "text-gray-400",
                              }}
                            />
                            <div className="flex items-center gap-2">
                              <div className="text-xs text-gray-400">
                                {new Date(
                                  message.time,
                                ).toLocaleString()}
                              </div>
                              {isExpanded ? (
                                <ChevronUp
                                  width={16}
                                  height={16}
                                  className="text-gray-400"
                                />
                              ) : (
                                <ChevronDown
                                  width={16}
                                  height={16}
                                  className="text-gray-400"
                                />
                              )}
                            </div>
                          </div>

                          {isExpanded && (
                            <>
                              <div className="mt-2">
                                <GmailBody
                                  email={message}
                                />
                                <EmailAttachments
                                  parts={
                                    message.payload
                                      ?.parts || []
                                  }
                                />
                              </div>

                              <div className="mt-4 flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  color="primary"
                                  variant="flat"
                                  startContent={
                                    <ArrowTurnBackwardIcon
                                      size={14}
                                    />
                                  }
                                  onPress={() =>
                                    handleReply(
                                      message,
                                    )
                                  }
                                >
                                  Reply
                                </Button>
                                <Button
                                  size="sm"
                                  color="primary"
                                  variant="flat"
                                  startContent={
                                    <ArrowLeftDoubleIcon
                                      size={14}
                                    />
                                  }
                                  onPress={() =>
                                    handleReplyAll(
                                      message,
                                    )
                                  }
                                >
                                  Reply All
                                </Button>
                                <Button
                                  size="sm"
                                  color="primary"
                                  variant="flat"
                                  startContent={
                                    <Share08Icon
                                      size={14}
                                    />
                                  }
                                  onPress={() =>
                                    handleForward(
                                      message,
                                    )
                                  }
                                >
                                  Forward
                                </Button>
                              </div>
                            </>
                          )}

                          {!isExpanded &&
                            message.snippet && (
                              <p className="mt-1 truncate text-sm text-gray-500">
                                {message.snippet}
                              </p>
                            )}
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
                      <EmailAttachments
                        parts={mail.payload?.parts || []}
                      />
                    </div>
                  </>
                ) : null}

                {mailId && !showReplyEditor && (
                  <SmartReplyChips
                    messageId={mailId}
                    onSelectReply={handleSmartReplySelect}
                  />
                )}

                {/* Task 51: Forward To field */}
                {showReplyEditor &&
                  replyTo &&
                  replyMode === "forward" && (
                    <div className="mb-2">
                      <Input
                        label="To"
                        placeholder="Enter recipient email"
                        value={forwardTo}
                        onValueChange={setForwardTo}
                        type="email"
                        variant="bordered"
                        size="sm"
                      />
                    </div>
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
              </>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
