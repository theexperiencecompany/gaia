"use client";

import {
  Button,
  Chip,
  FieldError,
  Input,
  Label,
  Modal,
  ScrollShadow,
  TextArea,
  TextField,
} from "@heroui/react";
import { Comment01Icon, HelpCircleIcon, PencilEdit01Icon } from "@icons";
import { useState } from "react";
import { z } from "zod";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { Separator } from "@/components/ui/separator";
import { supportApi } from "@/features/support/api/supportApi";
import { toast } from "@/lib/toast";
import type { SupportTicketData } from "@/types/features/supportTypes";

// Support ticket validation schema
const supportTicketSchema = z.object({
  type: z.enum(["support", "feature"], {
    error: "Support type is required",
  }),
  title: z
    .string()
    .min(1, "Title is required")
    .max(200, "Title must be under 200 characters"),
  description: z
    .string()
    .min(10, "Description must be at least 10 characters")
    .max(5000, "Description must be under 5,000 characters"),
});

interface SupportTicketCardProps {
  ticketData: SupportTicketData;
  onSubmitted?: () => void;
}

function EditTicketModal({
  isOpen,
  onClose,
  onSave,
  editData,
  onChange,
  errors,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  editData: SupportTicketData;
  onChange: (patch: Partial<SupportTicketData>) => void;
  errors: Record<string, string>;
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={onClose}>
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">
              Edit Support Ticket
            </Modal.Header>
            <Modal.Body>
              {/* Type Selection */}
              <div className="mb-4">
                <div className="mb-2 text-sm font-medium text-gray-200">
                  Type
                </div>
                <div className="flex gap-2">
                  <Chip
                    size="md"
                    variant="primary"
                    color={editData.type === "support" ? "accent" : "default"}
                    className="cursor-pointer"
                    onClick={() => onChange({ type: "support" })}
                  >
                    Support
                  </Chip>
                  <Chip
                    size="md"
                    variant="primary"
                    color={editData.type === "feature" ? "accent" : "default"}
                    className="cursor-pointer"
                    onClick={() => onChange({ type: "feature" })}
                  >
                    Feature Request
                  </Chip>
                </div>
                {errors.type && (
                  <div className="mt-1 text-xs text-red-500">{errors.type}</div>
                )}
              </div>

              {/* Title Field */}
              <div className="mb-4">
                <TextField
                  className={fieldVariants({ labelPlacement: "inside" })}
                  value={editData.title}
                  onChange={(value) => onChange({ title: value })}
                  isInvalid={!!errors.title}
                >
                  <Label>Title</Label>
                  <Input placeholder="Brief description of your issue or request" />
                  <FieldError>{errors.title}</FieldError>
                </TextField>
              </div>

              {/* Description Field */}
              <div>
                <TextField
                  className={fieldVariants({ labelPlacement: "inside" })}
                  value={editData.description}
                  onChange={(value) => onChange({ description: value })}
                  isInvalid={!!errors.description}
                >
                  <Label>Description</Label>
                  <TextArea
                    placeholder="Please provide detailed information about your issue or feature request"
                    rows={5}
                  />
                  <FieldError>{errors.description}</FieldError>
                </TextField>
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" onPress={onClose}>
                Cancel
              </Button>
              <Button onPress={onSave} variant="primary">
                Save Changes
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

export default function SupportTicketCard({
  ticketData,
  onSubmitted,
}: SupportTicketCardProps) {
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Only the user's edits are stored; the ticket prop stays the source of
  // truth and the edited view is derived during render, so new ticket data
  // can never leave a stale copy on screen.
  const [edits, setEdits] = useState<Partial<SupportTicketData>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const editData: SupportTicketData = { ...ticketData, ...edits };

  const validateForm = () => {
    try {
      supportTicketSchema.parse({
        type: editData.type,
        title: editData.title,
        description: editData.description,
      });

      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: Record<string, string> = {};
        error.issues.forEach((err) => {
          if (err.path[0]) {
            newErrors[err.path[0] as string] = err.message;
          }
        });
        setErrors(newErrors);
      }
      return false;
    }
  };

  const handleSubmit = async () => {
    if (!validateForm()) {
      toast.error("Please fix the validation errors");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await supportApi.submitRequest({
        type: editData.type,
        title: editData.title,
        description: editData.description,
      });

      if (result.success) {
        toast.success(
          `Support ticket submitted successfully! Ticket ID: ${result.ticket_id}`,
        );
        onSubmitted?.();
      } else {
        toast.error(result.message || "Failed to submit support ticket");
      }
    } catch (error) {
      console.error("Failed to submit support ticket:", error);
      toast.error("Failed to submit support ticket. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSave = () => {
    if (!validateForm()) {
      toast.error("Please fix the validation errors");
      return;
    }

    setIsEditModalOpen(false);
  };

  const handleEditClick = () => {
    setErrors({});
    setIsEditModalOpen(true);
  };

  const getTypeDisplay = () => {
    return editData.type === "feature" ? "Feature Request" : "Support Ticket";
  };

  const getTypeIcon = () => {
    return editData.type === "feature" ? (
      <Comment01Icon width={18} height={18} />
    ) : (
      <HelpCircleIcon width={18} height={18} />
    );
  };

  const getTypeColor = () => {
    return editData.type === "feature" ? "success" : "accent";
  };

  return (
    <>
      {/* Main Support Ticket Card */}
      <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-zinc-800">
        {/* Header with type indicator */}
        <div className="flex items-center justify-between px-6 py-1">
          <div className="flex flex-row items-center gap-2 pt-3 pb-2">
            {getTypeIcon()}
            <Chip size="sm" color={getTypeColor()} variant="soft">
              {getTypeDisplay()}
            </Chip>
          </div>
        </div>

        <div className="flex flex-col gap-1 px-6">
          {/* Title with Edit Button */}
          <div className="flex items-center justify-between">
            <div className="flex-1 text-lg font-semibold text-zinc-100">
              {editData.title}
            </div>
            <GaiaButton
              isIconOnly
              size="sm"
              variant="ghost"
              tone="faint"
              hoverTone="foreground"
              onPress={handleEditClick}
              className="h-8 w-8"
            >
              <PencilEdit01Icon color="currentColor" width={16} height={16} />
            </GaiaButton>
          </div>

          <Separator className="my-1.5 bg-zinc-700" />

          {/* User Info */}
          {(editData.user_name || editData.user_email) && (
            <>
              <div className="flex w-full items-center gap-2 text-sm text-gray-400">
                <span>From:</span>
                <span className="font-medium text-gray-200">
                  {editData.user_name || editData.user_email}
                  {editData.user_name && editData.user_email && (
                    <span className="ml-1 font-normal text-gray-400">
                      ({editData.user_email})
                    </span>
                  )}
                </span>
              </div>
              <Separator className="my-1.5 bg-zinc-700" />
            </>
          )}

          {/* Description */}
          <ScrollShadow className="relative z-[1] overflow-y-auto text-sm leading-relaxed whitespace-pre-line">
            <div className="pb-5">{editData.description}</div>
          </ScrollShadow>
        </div>

        {/* Submit Button */}
        <div className="flex justify-end px-6 pb-5">
          <GaiaButton
            shape="pill"
            onPress={handleSubmit}
            isPending={isSubmitting}
            className="font-medium"
            variant="primary"
          >
            {isSubmitting ? "Submitting..." : "Submit Ticket"}
          </GaiaButton>
        </div>
      </div>

      <EditTicketModal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSave}
        editData={editData}
        onChange={(patch) => setEdits((prev) => ({ ...prev, ...patch }))}
        errors={errors}
      />
    </>
  );
}
