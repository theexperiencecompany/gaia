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
import { ScrollShadow } from "@heroui/scroll-shadow";
import React, { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";

import { PencilEdit01Icon, Separator } from "@/components";
import { supportApi } from "@/features/support/api/supportApi";
import { HelpCircle, MessageSquare } from "@/icons";
import { SupportTicketData } from "@/types/features/supportTypes";

// Support ticket validation schema
const supportTicketSchema = z.object({
  type: z.enum(["support", "feature"], {
    required_error: "Support type is required",
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
  setEditData,
  errors,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  editData: SupportTicketData;
  setEditData: React.Dispatch<React.SetStateAction<SupportTicketData>>;
  errors: Record<string, string>;
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={onClose} size="lg">
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          Edit Support Ticket
        </ModalHeader>
        <ModalBody>
          {/* Type Selection */}
          <div className="mb-4">
            <div className="mb-2 text-sm font-medium text-gray-200">Type</div>
            <div className="flex gap-2">
              <Chip
                size="md"
                variant={editData.type === "support" ? "solid" : "bordered"}
                color={editData.type === "support" ? "primary" : "default"}
                className="cursor-pointer"
                onClick={() => setEditData({ ...editData, type: "support" })}
              >
                Support
              </Chip>
              <Chip
                size="md"
                variant={editData.type === "feature" ? "solid" : "bordered"}
                color={editData.type === "feature" ? "primary" : "default"}
                className="cursor-pointer"
                onClick={() => setEditData({ ...editData, type: "feature" })}
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
            <Input
              label="Title"
              placeholder="Brief description of your issue or request"
              value={editData.title}
              onChange={(e) =>
                setEditData({ ...editData, title: e.target.value })
              }
              isInvalid={!!errors.title}
              errorMessage={errors.title}
            />
          </div>

          {/* Description Field */}
          <div>
            <Textarea
              label="Description"
              placeholder="Please provide detailed information about your issue or feature request"
              value={editData.description}
              onChange={(e) =>
                setEditData({ ...editData, description: e.target.value })
              }
              minRows={5}
              maxRows={8}
              isInvalid={!!errors.description}
              errorMessage={errors.description}
            />
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="light" onPress={onClose}>
            Cancel
          </Button>
          <Button color="primary" onPress={onSave}>
            Save Changes
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default function SupportTicketCard({
  ticketData,
  onSubmitted,
}: SupportTicketCardProps) {
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editData, setEditData] = useState<SupportTicketData>(ticketData);
  const [errors, setErrors] = useState<Record<string, string>>({});

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
        error.errors.forEach((err) => {
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
      <MessageSquare width={18} height={18} />
    ) : (
      <HelpCircle width={18} height={18} />
    );
  };

  const getTypeColor = () => {
    return editData.type === "feature" ? "success" : "primary";
  };

  return (
    <>
      {/* Main Support Ticket Card */}
      <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-zinc-800">
        {/* Header with type indicator */}
        <div className="flex items-center justify-between px-6 py-1">
          <div className="flex flex-row items-center gap-2 pt-3 pb-2">
            {getTypeIcon()}
            <Chip size="sm" color={getTypeColor()} variant="flat">
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
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onPress={handleEditClick}
              className="h-8 w-8 text-zinc-500 hover:text-zinc-200"
            >
              <PencilEdit01Icon color="currentColor" width={16} height={16} />
            </Button>
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
          <ScrollShadow className="relative z-[1] overflow-y-auto pb-5 text-sm leading-relaxed whitespace-pre-line text-zinc-200">
            {editData.description}
          </ScrollShadow>
        </div>

        {/* Submit Button */}
        <div className="flex justify-end px-6 pb-5">
          <Button
            color="primary"
            onPress={handleSubmit}
            isLoading={isSubmitting}
            radius="full"
            className="font-medium"
          >
            {isSubmitting ? "Submitting..." : "Submit Ticket"}
          </Button>
        </div>
      </div>

      <EditTicketModal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSave}
        editData={editData}
        setEditData={setEditData}
        errors={errors}
      />
    </>
  );
}
