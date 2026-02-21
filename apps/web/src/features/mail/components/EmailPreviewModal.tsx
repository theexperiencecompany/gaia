"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Cancel01Icon } from "@icons";
import { useEffect, useState } from "react";
import { mailApi as EmailsAPI } from "@/features/mail/api/mailApi";
import { toast } from "@/lib/toast";

import { NotificationsAPI } from "../../../services/api/notifications";

interface EmailPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  subject: string;
  body: string;
  recipients: string[];
  mode?: "view" | "edit";
  onEmailSent?: () => void; // Callback for when email is sent successfully
  recipient_query?: string; // Optional query context
  notificationId?: string; // Notification ID for marking action as executed
  actionId?: string; // Action ID for marking action as executed
}

export function EmailPreviewModal({
  isOpen,
  onClose,
  subject: initialSubject,
  body: initialBody,
  recipients: initialRecipients,
  mode = "edit",
  onEmailSent,
  recipient_query,
  notificationId,
  actionId,
}: EmailPreviewModalProps) {
  const [subject, setSubject] = useState(initialSubject);
  const [body, setBody] = useState(initialBody);
  const [emailChips, setEmailChips] = useState<
    Array<{ email: string; isValid: boolean }>
  >(initialRecipients.map((email) => ({ email, isValid: true })));
  const [currentInput, setCurrentInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [errors, setErrors] = useState<{
    subject?: string;
    body?: string;
    recipients?: string;
  }>({});

  // Clear recipient errors when chips change
  useEffect(() => {
    if (errors.recipients && emailChips.length > 0) {
      setErrors((prev) => ({ ...prev, recipients: undefined }));
    }
  }, [emailChips, errors.recipients]);

  // Email validation function
  const isValidEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email.trim());
  };

  // Add email chip
  const addEmailChip = (email: string) => {
    const trimmedEmail = email.trim();
    if (
      trimmedEmail &&
      !emailChips.some((chip) => chip.email === trimmedEmail)
    ) {
      const newChip = {
        email: trimmedEmail,
        isValid: isValidEmail(trimmedEmail),
      };
      setEmailChips((prev) => [...prev, newChip]);
      setCurrentInput("");
    }
  };

  // Remove email chip
  const removeEmailChip = (emailToRemove: string) => {
    setEmailChips((prev) =>
      prev.filter((chip) => chip.email !== emailToRemove),
    );
  };

  // Handle input key events
  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === " ") {
      e.preventDefault();
      if (currentInput.trim()) {
        addEmailChip(currentInput);
      }
    } else if (
      e.key === "Backspace" &&
      !currentInput &&
      emailChips.length > 0
    ) {
      // Remove last chip if input is empty and backspace is pressed
      const lastChip = emailChips[emailChips.length - 1];
      removeEmailChip(lastChip.email);
    }
  };

  // Handle paste event
  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pastedText = e.clipboardData.getData("text");
    const emails = pastedText.split(/[,;\s]+/).filter((email) => email.trim());

    emails.forEach((email) => {
      if (email.trim()) {
        addEmailChip(email);
      }
    });
  };

  // Validation function
  const validateForm = () => {
    const newErrors: typeof errors = {};

    // Validate subject
    if (!subject.trim()) {
      newErrors.subject = "Subject is required";
    }

    // Validate body
    if (!body.trim()) {
      newErrors.body = "Email body is required";
    }

    // Validate recipients
    if (emailChips.length === 0) {
      newErrors.recipients = "At least one recipient is required";
    } else {
      const invalidChips = emailChips.filter((chip) => !chip.isValid);
      if (invalidChips.length > 0) {
        newErrors.recipients = `Invalid email addresses: ${invalidChips.map((chip) => chip.email).join(", ")}`;
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSendEmail = async () => {
    if (!validateForm()) {
      toast.error("Please fix the validation errors before sending");
      return;
    }

    setIsSending(true);
    try {
      const formData = new FormData();
      formData.append("to", emailChips.map((chip) => chip.email).join(", "));
      formData.append("subject", subject);
      formData.append("body", body);

      // The apiService.post will handle success/error toasts automatically
      // based on the successMessage and errorMessage options in the API
      await EmailsAPI.sendEmail(formData);

      // Mark the notification action as executed if provided (only once)
      if (notificationId && actionId) {
        try {
          await NotificationsAPI.executeAction(notificationId, actionId);
        } catch (error) {
          console.error(
            "Failed to mark notification action as executed:",
            error,
          );
          // Don't show error to user as email was sent successfully
        }
      }

      onEmailSent?.(); // Call the callback if provided
      onClose();
    } catch (error) {
      console.error("Failed to send email:", error);
      // Error toast is already shown by apiService.post
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside">
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Review & Send Email</h2>
          <p className="text-sm text-gray-600">
            {recipient_query
              ? `AI composed this email based on: "${recipient_query}"`
              : "Review and edit your email before sending"}
          </p>
        </ModalHeader>

        <ModalBody className="py-6">
          <div className="space-y-6">
            {/* Recipients */}
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground">
                To <span className="text-danger">*</span>
              </div>
              <div
                className={`min-h-[56px] rounded-xl border-2 bg-default-100 p-3 transition-colors focus-within:border-primary ${
                  errors.recipients ? "border-danger" : "border-default-200"
                }`}
              >
                <div className="flex flex-wrap gap-2">
                  {/* Email Chips */}
                  {emailChips.map((chip) => (
                    <Chip
                      key={chip.email}
                      variant="flat"
                      color={chip.isValid ? "primary" : "danger"}
                      size="sm"
                      endContent={
                        mode === "edit" && (
                          <button
                            type="button"
                            onClick={() => removeEmailChip(chip.email)}
                            className="ml-1 rounded-full p-0.5 transition-colors hover:bg-white/20"
                          >
                            <Cancel01Icon size={12} />
                          </button>
                        )
                      }
                      className="max-w-[200px]"
                    >
                      <span className="truncate text-xs">{chip.email}</span>
                    </Chip>
                  ))}

                  {/* Input Field */}
                  {mode === "edit" && (
                    <input
                      type="text"
                      value={currentInput}
                      onChange={(e) => setCurrentInput(e.target.value)}
                      onKeyDown={handleInputKeyDown}
                      onPaste={handlePaste}
                      onBlur={() => {
                        if (currentInput.trim()) {
                          addEmailChip(currentInput);
                        }
                      }}
                      placeholder={
                        emailChips.length === 0
                          ? "Enter email addresses..."
                          : "Add more emails..."
                      }
                      className="min-w-[120px] flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-default-400"
                    />
                  )}
                </div>
              </div>
              {errors.recipients && (
                <p className="text-sm text-danger">{errors.recipients}</p>
              )}
              <p className="text-xs text-default-500">
                Press Enter, comma, or space to add emails. Use Backspace to
                remove the last email.
              </p>
            </div>

            {/* Subject */}
            <div className="space-y-2">
              <Input
                label="Subject"
                placeholder="Email subject"
                value={subject}
                onChange={(e) => {
                  setSubject(e.target.value);
                  // Clear error when user starts typing
                  if (errors.subject) {
                    setErrors((prev) => ({ ...prev, subject: undefined }));
                  }
                }}
                isDisabled={mode === "view"}
                isInvalid={!!errors.subject}
                errorMessage={errors.subject}
                isRequired
                variant="bordered"
              />
            </div>

            {/* Body */}
            <div className="space-y-2">
              <Textarea
                label="Body"
                placeholder="Email body"
                value={body}
                onChange={(e) => {
                  setBody(e.target.value);
                  // Clear error when user starts typing
                  if (errors.body) {
                    setErrors((prev) => ({ ...prev, body: undefined }));
                  }
                }}
                isDisabled={mode === "view"}
                isInvalid={!!errors.body}
                errorMessage={errors.body}
                isRequired
                variant="bordered"
                minRows={12}
                maxRows={20}
              />
            </div>
          </div>
        </ModalBody>

        <ModalFooter>
          <Button variant="light" onPress={onClose} isDisabled={isSending}>
            Cancel
          </Button>

          {mode === "edit" && (
            <Button
              color="primary"
              onPress={handleSendEmail}
              isDisabled={isSending}
              isLoading={isSending}
            >
              Send Email
            </Button>
          )}
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
