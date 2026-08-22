"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Input, Textarea } from "@heroui/input";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Cancel01Icon, PencilEdit01Icon, PlusSignIcon } from "@icons";
import DOMPurify from "dompurify";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { ChevronRight, Gmail } from "@/components/shared/icons";
import { Separator } from "@/components/ui/separator";
import { mailApi } from "@/features/mail/api/mailApi";
import { toast } from "@/lib/toast";

// Email validation schema
const emailComposeSchema = z.object({
  to: z
    .array(z.email("Invalid email address"))
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

const emailValidationSchema = z.email("Invalid email address");

type RecipientField = "to" | "cc" | "bcc";

const RECIPIENT_FIELDS: {
  field: RecipientField;
  label: string;
  addLabel: string;
}[] = [
  { field: "to", label: "To", addLabel: "Add Recipients" },
  { field: "cc", label: "Cc", addLabel: "Add Cc" },
  { field: "bcc", label: "Bcc", addLabel: "Add Bcc" },
];

type RecipientMap = Record<RecipientField, string[]>;

function HtmlEmailBody({ html }: { html: string }) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const shadowRoot =
      hostRef.current.shadowRoot ||
      hostRef.current.attachShadow({ mode: "open" });
    shadowRoot.innerHTML = "";
    const wrapper = document.createElement("div");
    wrapper.style.font = "inherit";
    wrapper.style.color = "inherit";
    wrapper.style.lineHeight = "1.5";
    wrapper.innerHTML = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
    shadowRoot.appendChild(wrapper);
  }, [html]);

  return <div ref={hostRef} />;
}

interface EmailData {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
}

interface EmailComposeCardProps {
  emailData: EmailData;
  onSent?: () => void;
}

function seedRecipients(data: EmailData): RecipientMap {
  const to = data.to || [];
  return {
    to: to.length === 1 ? [to[0]] : [],
    cc: data.cc || [],
    bcc: data.bcc || [],
  };
}

/**
 * Card header with status chip — toggles the card open/collapsed.
 */
function ComposeHeader({
  isDraft,
  hasThread,
  isCollapsed,
  onToggle,
}: {
  isDraft: boolean;
  hasThread: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      fullWidth
      disableRipple
      variant="light"
      radius="none"
      onPress={onToggle}
      aria-expanded={!isCollapsed}
      className="h-auto justify-between px-6 pt-4 pb-3"
    >
      <span className="flex flex-row items-center gap-2">
        <Gmail width={18} height={18} />
        <span className="text-sm font-medium">
          {isDraft ? "Email Draft" : "Compose Email"}
        </span>
        {hasThread && (
          <Chip size="sm" variant="flat" color="primary">
            Reply
          </Chip>
        )}
      </span>
      <ChevronRight
        className={`h-4 w-4 text-zinc-400 transition-transform ${
          isCollapsed ? "rotate-0" : "rotate-90"
        }`}
      />
    </Button>
  );
}

function EmailBodyPreview({
  html,
  onEdit,
}: {
  html: string;
  onEdit: () => void;
}) {
  return (
    <ScrollShadow className="relative z-1 max-h-46 overflow-y-auto pb-5 text-sm leading-relaxed text-zinc-200">
      <div className="absolute top-0 right-0 z-2 flex w-full justify-end">
        <Button variant="light" size="sm" isIconOnly onPress={onEdit}>
          <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
        </Button>
      </div>
      <HtmlEmailBody html={html} />
    </ScrollShadow>
  );
}

/**
 * Recipient rows, subject summary and body preview of an expanded compose card.
 */
function ComposeFields({
  recipients,
  onEditField,
  subject,
  body,
  onEdit,
}: {
  recipients: RecipientMap;
  onEditField: (field: RecipientField) => void;
  subject: string;
  body: string;
  onEdit: () => void;
}) {
  return (
    <div className="flex flex-col gap-1 px-6">
      {RECIPIENT_FIELDS.map(({ field, label, addLabel }) => (
        <div key={field}>
          <RecipientRow
            label={label}
            addLabel={addLabel}
            emails={recipients[field]}
            onEdit={() => onEditField(field)}
          />
          <Separator className="my-1.5 bg-zinc-700" />
        </div>
      ))}
      <div className="flex w-full items-center justify-between text-sm text-gray-400">
        <div className="flex items-center gap-2">
          <span>Subject:</span>
          <span className="font-medium text-gray-200">{subject}</span>
        </div>

        <Button variant="light" size="sm" isIconOnly onPress={onEdit}>
          <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
        </Button>
      </div>
      <Separator className="my-1.5 bg-zinc-700" />

      <EmailBodyPreview html={body} onEdit={onEdit} />
    </div>
  );
}

function RecipientRow({
  label,
  addLabel,
  emails,
  onEdit,
}: {
  label: string;
  addLabel: string;
  emails: string[];
  onEdit: () => void;
}) {
  return (
    <div className="flex items-center gap-2 text-sm text-zinc-400">
      <span>{label}:</span>
      <span className="flex w-full items-center justify-between font-medium text-zinc-200">
        {emails.join(", ") || ""}
        <Button
          size="sm"
          onPress={onEdit}
          variant={emails.length === 0 ? "flat" : "light"}
          isIconOnly={emails.length !== 0}
          endContent={
            emails.length === 0 ? (
              ""
            ) : (
              <PencilEdit01Icon className="h-5 w-5 text-zinc-500" />
            )
          }
        >
          {emails.length === 0 ? addLabel : ``}
        </Button>
      </span>
    </div>
  );
}

function EditEmailModal({
  isOpen,
  onClose,
  onSave,
  initialData,
  errors,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: (draft: { subject: string; body: string }) => void;
  initialData: EmailData;
  errors: Record<string, string>;
}) {
  // Seeded from the current data at mount; the parent remounts this modal
  // (keyed by an edit session counter) each time it opens.
  const [draft, setDraft] = useState({
    subject: initialData.subject,
    body: initialData.body,
  });

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
              value={draft.subject}
              onChange={(e) =>
                setDraft((d) => ({ ...d, subject: e.target.value }))
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
              value={draft.body}
              onChange={(e) =>
                setDraft((d) => ({ ...d, body: e.target.value }))
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
              onPress={() => onSave(draft)}
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
  title,
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
  title: string;
  suggestions: string[];
  selectedEmails: string[];
  setSelectedEmails: React.Dispatch<React.SetStateAction<string[]>>;
  customEmailInput: string;
  setCustomEmailInput: React.Dispatch<React.SetStateAction<string>>;
  customEmailError: string;
  setCustomEmailError: React.Dispatch<React.SetStateAction<string>>;
  handleAddCustomEmail: () => void;
}) {
  const selectedSet = new Set(selectedEmails);

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

  const handleCustomEmailKeyDown = (e: React.KeyboardEvent) => {
    // Bail on IME composition so Enter confirming a candidate doesn't submit.
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddCustomEmail();
    }
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={onClose} size="sm">
      <ModalContent>
        <ModalBody>
          <div className="pt-2 text-sm font-medium">{title}</div>

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {suggestions.map((email) => (
                <Chip
                  key={email}
                  size="sm"
                  variant="flat"
                  color={selectedSet.has(email) ? "primary" : "default"}
                  className="cursor-pointer text-xs"
                  onClick={() => handleSuggestionToggle(email)}
                  endContent={
                    selectedSet.has(email) ? (
                      <Cancel01Icon className="h-3 w-3" />
                    ) : null
                  }
                >
                  {email}
                </Chip>
              ))}
            </div>
          )}

          {suggestions.length > 0 && <Divider className="my-2 bg-zinc-700" />}

          <div className="flex gap-2">
            <Input
              placeholder="Add email..."
              value={customEmailInput}
              onChange={(e) => {
                setCustomEmailInput(e.target.value);
                setCustomEmailError("");
              }}
              onKeyDown={handleCustomEmailKeyDown}
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
              <PlusSignIcon className="h-4 w-4" />
            </Button>
          </div>

          {/* Action Buttons */}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="light" size="sm" onPress={onClose}>
              Cancel
            </Button>
            <Button color="primary" size="sm" onPress={onConfirm}>
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
  // Card starts expanded; users can collapse it to a compact header.
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [activeRecipientField, setActiveRecipientField] =
    useState<RecipientField | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Bumped every time the edit modal opens so it remounts with a fresh draft.
  const [editSession, setEditSession] = useState(0);
  // Subject/body edits committed from the edit modal; null until first save.
  const [savedEdits, setSavedEdits] = useState<{
    subject: string;
    body: string;
  } | null>(null);

  // Selected recipients per field, seeded from the agent-resolved emailData.
  const [recipients, setRecipients] = useState<RecipientMap>(() =>
    seedRecipients(emailData),
  );

  // Draft copy of the active field's selection, edited inside the recipient
  // modal and committed to `recipients` only on confirm (Cancel discards it).
  const [draftEmails, setDraftEmails] = useState<string[]>([]);

  // Addresses added manually by the user, shown as suggestion chips alongside
  // the agent-provided ones.
  const [customSuggestions, setCustomSuggestions] = useState<RecipientMap>({
    to: [],
    cc: [],
    bcc: [],
  });

  // Custom email input state
  const [customEmailInput, setCustomEmailInput] = useState("");
  const [customEmailError, setCustomEmailError] = useState("");

  // Suggestion chips per field (agent-resolved addresses + any custom ones),
  // derived instead of stored so they always follow emailData.
  const recipientSuggestions: RecipientMap = {
    to: [...(emailData.to || []), ...customSuggestions.to],
    cc: [...(emailData.cc || []), ...customSuggestions.cc],
    bcc: [...(emailData.bcc || []), ...customSuggestions.bcc],
  };

  // Subject/body follow the agent-resolved data until the user saves an edit.
  const editData: EmailData = savedEdits
    ? { ...emailData, ...savedEdits }
    : emailData;

  const activeSuggestions = activeRecipientField
    ? recipientSuggestions[activeRecipientField]
    : [];

  // Commit the modal's draft selection back to the active field, then close.
  const commitRecipientDraft = () => {
    if (activeRecipientField) {
      setRecipients((prev) => ({
        ...prev,
        [activeRecipientField]: draftEmails,
      }));
    }
    setActiveRecipientField(null);
  };

  const validateForm = (data: { subject: string; body: string }) => {
    try {
      emailComposeSchema.parse({
        to: recipients.to,
        subject: data.subject,
        body: data.body,
      });

      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: Record<string, string> = {};
        error.issues.forEach((err) => {
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
        setCustomEmailError(error.issues[0]?.message || "Invalid email");
      }
      return false;
    }
  };

  const handleSend = async () => {
    if (recipients.to.length === 0) {
      toast.error("Please select at least one recipient");
      return;
    }

    if (!validateForm({ subject: editData.subject, body: editData.body })) {
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
        formData.append("to", recipients.to.join(", "));
        formData.append("subject", editData.subject);
        formData.append("body", editData.body);
        if (recipients.cc.length > 0) {
          formData.append("cc", recipients.cc.join(", "));
        }
        if (recipients.bcc.length > 0) {
          formData.append("bcc", recipients.bcc.join(", "));
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

  const handleSave = (draft: { subject: string; body: string }) => {
    if (!validateForm(draft)) {
      toast.error("Please fix the validation errors");
      return;
    }

    setSavedEdits(draft);
    setIsEditModalOpen(false);
    toast.success("Email updated successfully!");
  };

  const handleEditClick = () => {
    setErrors({});
    setEditSession((session) => session + 1);
    setIsEditModalOpen(true);
  };

  const openRecipientModal = (field: RecipientField) => {
    setCustomEmailInput("");
    setCustomEmailError("");
    setDraftEmails(recipients[field]);
    setActiveRecipientField(field);
  };

  // Add a manually typed email to the active field's draft selection.
  const handleAddCustomEmail = () => {
    if (!activeRecipientField) return;

    const trimmedEmail = customEmailInput.trim();

    if (!trimmedEmail) {
      setCustomEmailError("Please enter an email address");
      return;
    }

    if (!validateCustomEmail(trimmedEmail)) {
      return;
    }

    if (draftEmails.includes(trimmedEmail)) {
      setCustomEmailError("Email already added");
      return;
    }

    setDraftEmails((prev) => [...prev, trimmedEmail]);

    if (!recipientSuggestions[activeRecipientField].includes(trimmedEmail)) {
      const field = activeRecipientField;
      setCustomSuggestions((prev) => ({
        ...prev,
        [field]: [...prev[field], trimmedEmail],
      }));
    }

    setCustomEmailInput("");
    setCustomEmailError("");
    toast.success(`Added ${trimmedEmail}`);
  };

  const activeFieldConfig = RECIPIENT_FIELDS.find(
    (f) => f.field === activeRecipientField,
  );

  return (
    <>
      {/* Main Email Card */}
      <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-zinc-800">
        <ComposeHeader
          isDraft={!!emailData.draft_id}
          hasThread={!!emailData.thread_id}
          isCollapsed={isCollapsed}
          onToggle={() => setIsCollapsed((prev) => !prev)}
        />

        <AnimatePresence initial={false}>
          {!isCollapsed && (
            <m.div
              key="compose-body"
              layout
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <ComposeFields
                recipients={recipients}
                onEditField={openRecipientModal}
                subject={editData.subject}
                body={editData.body}
                onEdit={handleEditClick}
              />
              <div className="flex justify-end px-6 pb-5">
                <Button
                  color="primary"
                  onPress={handleSend}
                  isLoading={isSending}
                  isDisabled={recipients.to.length === 0}
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
            </m.div>
          )}
        </AnimatePresence>
      </div>

      {/* Keyed by session so the draft re-seeds from the current data on open */}
      <EditEmailModal
        key={editSession}
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSave}
        initialData={editData}
        errors={errors}
      />

      <RecipientSelectionModal
        isOpen={activeRecipientField !== null}
        onClose={() => setActiveRecipientField(null)}
        onConfirm={commitRecipientDraft}
        title={activeFieldConfig ? `${activeFieldConfig.label} recipients` : ""}
        suggestions={activeSuggestions}
        selectedEmails={draftEmails}
        setSelectedEmails={setDraftEmails}
        customEmailInput={customEmailInput}
        setCustomEmailInput={setCustomEmailInput}
        customEmailError={customEmailError}
        setCustomEmailError={setCustomEmailError}
        handleAddCustomEmail={handleAddCustomEmail}
      />
    </>
  );
}
