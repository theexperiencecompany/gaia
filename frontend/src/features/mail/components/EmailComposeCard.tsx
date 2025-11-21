import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input, Textarea } from "@heroui/input";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import DOMPurify from "dompurify";
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";

import { Gmail, PencilEdit01Icon, Separator } from "@/components";
import { mailApi } from "@/features/mail/api/mailApi";
import { Plus, X } from "@/icons";

// Email validation schema
const emailComposeSchema = z.object({
  to: z
    .array(z.string().email("Invalid email address"))
    .min(1, "At least one recipient is required"),
  subject: z
    .string()
    .min(1, "Subject is required")
    .max(200, "Subject must be under 200 characters"),
  body: z
    .string()
    .min(1, "Email body is required")
    .max(10000, "Email body must be under 10,000 characters"),
});

const emailValidationSchema = z.string().email("Invalid email address");

interface EmailData {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
}

interface EmailComposeCardProps {
  emailData: EmailData;
  onSent?: () => void;
}

function EditEmailModal({
  isOpen,
  onClose,
  onSave,
  editData,
  setEditData,
  errors,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  editData: EmailData;
  setEditData: React.Dispatch<React.SetStateAction<EmailData>>;
  errors: Record<string, string>;
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={onClose} size="2xl">
      <ModalContent className="w-full max-w-md">
        <ModalBody>
          <div className="pt-2 text-sm font-medium">Edit Email</div>
          {/* Subject Field */}
          <div className="mb-1">
            <Input
              label="Subject"
              placeholder="Subject"
              value={editData.subject}
              onChange={(e) =>
                setEditData({ ...editData, subject: e.target.value })
              }
              isInvalid={!!errors.subject}
              errorMessage={errors.subject}
              size="sm"
            />
          </div>
          {/* Body Field */}
          <div>
            <Textarea
              label="Message"
              placeholder="Your message"
              value={editData.body}
              onChange={(e) =>
                setEditData({ ...editData, body: e.target.value })
              }
              minRows={5}
              maxRows={8}
              isInvalid={!!errors.body}
              errorMessage={errors.body}
              size="sm"
            />
          </div>
          {/* Action Buttons */}
          <div className="mt-4 flex justify-end gap-2">
            <Button
              variant="light"
              size="sm"
              onPress={onClose}
              className="h-7 px-2 text-xs text-gray-300"
            >
              Cancel
            </Button>
            <Button
              color="primary"
              size="sm"
              onPress={onSave}
              className="h-7 px-3 text-xs font-medium"
            >
              Save
            </Button>
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

function RecipientSelectionModal({
  isOpen,
  onClose,
  onConfirm,
  suggestions,
  selectedEmails,
  setSelectedEmails,
  customEmailInput,
  setCustomEmailInput,
  customEmailError,
  setCustomEmailError,
  handleAddCustomEmail,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  suggestions: string[];
  selectedEmails: string[];
  setSelectedEmails: React.Dispatch<React.SetStateAction<string[]>>;
  customEmailInput: string;
  setCustomEmailInput: React.Dispatch<React.SetStateAction<string>>;
  customEmailError: string;
  setCustomEmailError: React.Dispatch<React.SetStateAction<string>>;
  handleAddCustomEmail: () => void;
}) {
  const handleSuggestionToggle = (email: string) => {
    setSelectedEmails((prev) => {
      if (prev.includes(email)) {
        // Remove from selected
        return prev.filter((e) => e !== email);
      } else {
        // Add to selected
        return [...prev, email];
      }
    });
  };

  const handleCustomEmailKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddCustomEmail();
    }
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={onClose} size="sm">
      <ModalContent>
        <ModalBody>
          <div className="pt-2 text-sm font-medium">Email Suggestions</div>

          {/* Suggestions */}
          <div className="flex flex-wrap gap-2">
            {suggestions.map((email) => (
              <Chip
                key={email}
                size="sm"
                variant="flat"
                color={selectedEmails.includes(email) ? "primary" : "default"}
                className="cursor-pointer text-xs"
                onClick={() => handleSuggestionToggle(email)}
                endContent={
                  selectedEmails.includes(email) ? (
                    <X className="h-3 w-3" />
                  ) : null
                }
              >
                {email}
              </Chip>
            ))}
          </div>

          <hr className="my-2 border-zinc-700" />

          <div className="flex gap-2">
            <Input
              placeholder="Add email..."
              value={customEmailInput}
              onChange={(e) => {
                setCustomEmailInput(e.target.value);
                setCustomEmailError("");
              }}
              onKeyDown={handleCustomEmailKeyPress}
              size="sm"
              isInvalid={!!customEmailError}
              errorMessage={customEmailError}
            />
            <Button
              size="sm"
              color="primary"
              onPress={handleAddCustomEmail}
              isIconOnly
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          {/* Action Buttons */}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="light" size="sm" onPress={onClose}>
              Cancel
            </Button>
            <Button
              color="primary"
              size="sm"
              onPress={onConfirm}
              isDisabled={selectedEmails.length === 0}
            >
              Done ({selectedEmails.length})
            </Button>
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

export default function EmailComposeCard({
  emailData,
  onSent,
}: EmailComposeCardProps) {
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isRecipientModalOpen, setIsRecipientModalOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [editData, setEditData] = useState<EmailData>(emailData);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Suggestions come from emailData.to - these are resolved email addresses from the agent
  const [suggestions, setSuggestions] = useState<string[]>(emailData.to || []);

  // Selected emails state - starts with emails from emailData (resolved by agent)
  const [selectedEmails, setSelectedEmails] = useState<string[]>(
    emailData.to || [],
  );

  // Custom email input state
  const [customEmailInput, setCustomEmailInput] = useState("");
  const [customEmailError, setCustomEmailError] = useState("");

  // Initialize with empty emails array - user must select recipients
  // If there's only one email, select it by default
  useEffect(() => {
    const suggestions = emailData.to || [];
    setEditData((prev) => ({ ...prev, to: [] }));
    setSuggestions(suggestions);

    // If there's exactly one email suggestion, select it by default
    if (suggestions.length === 1) setSelectedEmails([suggestions[0]]);
    else setSelectedEmails([]);
  }, [emailData.to]);

  const validateForm = () => {
    try {
      emailComposeSchema.parse({
        to: selectedEmails,
        subject: editData.subject,
        body: editData.body,
      });

      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: Record<string, string> = {};
        error.errors.forEach((err) => {
          if (err.path[0]) {
            newErrors[err.path[0].toString()] = err.message;
          }
        });
        setErrors(newErrors);
      }
      return false;
    }
  };

  const validateCustomEmail = (email: string): boolean => {
    try {
      emailValidationSchema.parse(email);
      setCustomEmailError("");
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        setCustomEmailError(error.errors[0]?.message || "Invalid email");
      }
      return false;
    }
  };

  const handleSend = async () => {
    if (selectedEmails.length === 0) {
      toast.error("Please select at least one recipient");
      return;
    }

    if (!validateForm()) {
      toast.error("Please fix the validation errors");
      return;
    }

    setIsSending(true);
    try {
      // Check if this is a draft (has draft_id) or needs to be sent directly
      if (emailData.draft_id) {
        // Send existing draft
        const result = await mailApi.sendDraft(emailData.draft_id);
        if (result.successful) {
          toast.success("Draft sent successfully!");
          onSent?.();
        } else {
          toast.error("Failed to send draft");
        }
      } else {
        // Send email directly (existing logic)
        const formData = new FormData();
        formData.append("to", selectedEmails.join(", "));
        formData.append("subject", editData.subject);
        formData.append("body", editData.body);
        formData.append("is_html", String(emailData.is_html || false));
        if (emailData.bcc && emailData.bcc.length > 0) {
          formData.append("bcc", emailData.bcc.join(", "));
        }
        if (emailData.cc && emailData.cc.length > 0) {
          formData.append("cc", emailData.cc.join(", "));
        }
        if (emailData.thread_id) {
          formData.append("thread_id", emailData.thread_id);
        }

        await mailApi.sendEmail(formData);
      }
    } catch (error) {
      console.error("Error sending email:", error);
      toast.error("Failed to send email");
    } finally {
      setIsSending(false);
    }
  };

  const handleSave = () => {
    if (!validateForm()) {
      toast.error("Please fix the validation errors");
      return;
    }

    const updatedData = {
      ...editData,
      to: selectedEmails,
    };

    setEditData(updatedData);
    setIsEditModalOpen(false);
    toast.success("Email updated successfully!");
  };

  const handleEditClick = () => {
    setErrors({});
    setIsEditModalOpen(true);
  };

  // Handle custom email addition
  const handleAddCustomEmail = () => {
    const trimmedEmail = customEmailInput.trim();

    if (!trimmedEmail) {
      setCustomEmailError("Please enter an email address");
      return;
    }

    if (!validateCustomEmail(trimmedEmail)) {
      return;
    }

    if (selectedEmails.includes(trimmedEmail)) {
      setCustomEmailError("Email already selected");
      return;
    }

    // Add to selected emails
    setSelectedEmails((prev) => [...prev, trimmedEmail]);

    // Add to suggestions if not already there
    if (!suggestions.includes(trimmedEmail)) {
      setSuggestions((prev) => [...prev, trimmedEmail]);
    }

    // Clear input
    setCustomEmailInput("");
    setCustomEmailError("");
    toast.success(`Added ${trimmedEmail}`);
  };

  // const handleRemoveSelectedEmail = (email: string) => {
  //   setSelectedEmails((prev) => prev.filter((e) => e !== email));
  // };

  const handleConfirmRecipients = () => {
    setEditData((prev) => ({ ...prev, to: selectedEmails }));
    setIsRecipientModalOpen(false);
  };

  // Filter suggestions based on search term - commented out as not used
  // const filteredSuggestions = suggestions.filter((email) =>
  //   email.toLowerCase().includes(_searchTerm.toLowerCase()),
  // );

  return (
    <>
      {/* Main Email Card - Redesigned UI */}
      <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-zinc-800">
        {/* Header with status chip */}
        <div className="flex items-center justify-between px-6 py-1">
          <div className="flex flex-row items-center gap-2 pt-3 pb-2">
            <Gmail width={18} height={18} />
            <span className="text-sm font-medium">
              {emailData.draft_id ? "Email Draft" : "Compose Email"}
            </span>
            {emailData.thread_id && (
              <Chip size="sm" variant="flat" color="primary">
                Reply
              </Chip>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1 px-6">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <span>To:</span>
            <span className="flex w-full items-center justify-between font-medium text-zinc-200">
              {selectedEmails.join(", ") || ""}
              <Button
                size="sm"
                onPress={() => setIsRecipientModalOpen(true)}
                variant={selectedEmails.length === 0 ? "flat" : "light"}
                isIconOnly={selectedEmails.length === 0 ? false : true}
                endContent={
                  selectedEmails.length === 0 ? (
                    ""
                  ) : (
                    <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
                  )
                }
              >
                {selectedEmails.length === 0 ? "Add Recipients" : ``}
              </Button>
            </span>
          </div>
          <Separator className="my-1.5 bg-zinc-700" />
          <div className="flex w-full items-center justify-between text-sm text-gray-400">
            <div className="flex items-center gap-2">
              <span>Subject:</span>
              <span className="font-medium text-gray-200">
                {editData.subject}
              </span>
            </div>

            <Button
              variant="light"
              size="sm"
              isIconOnly
              onPress={handleEditClick}
            >
              <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
            </Button>
          </div>
          <Separator className="my-1.5 bg-zinc-700" />

          <ScrollShadow className="relative z-[1] max-h-46 overflow-y-auto pb-5 text-sm leading-relaxed whitespace-pre-line text-zinc-200">
            <div className="absolute top-0 right-0 z-[2] flex w-full justify-end">
              <Button
                variant="light"
                size="sm"
                isIconOnly
                onPress={handleEditClick}
              >
                <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
              </Button>
            </div>
            {emailData.is_html ? (
              <div
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(editData.body),
                }}
              />
            ) : (
              editData.body
            )}
          </ScrollShadow>
        </div>
        <div className="flex justify-end px-6 pb-5">
          <Button
            color="primary"
            onPress={handleSend}
            isLoading={isSending}
            isDisabled={selectedEmails.length === 0}
            radius="full"
            className="font-medium"
          >
            {isSending
              ? "Sending..."
              : emailData.draft_id
                ? "Send Draft"
                : "Send"}
          </Button>
        </div>
      </div>

      <EditEmailModal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSave}
        editData={editData}
        setEditData={setEditData}
        errors={errors}
      />

      <RecipientSelectionModal
        isOpen={isRecipientModalOpen}
        onClose={() => setIsRecipientModalOpen(false)}
        onConfirm={handleConfirmRecipients}
        suggestions={suggestions}
        selectedEmails={selectedEmails}
        setSelectedEmails={setSelectedEmails}
        customEmailInput={customEmailInput}
        setCustomEmailInput={setCustomEmailInput}
        customEmailError={customEmailError}
        setCustomEmailError={setCustomEmailError}
        handleAddCustomEmail={handleAddCustomEmail}
      />
    </>
  );
}
