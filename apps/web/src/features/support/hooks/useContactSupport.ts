"use client";

import { useState } from "react";
import { toast } from "@/lib/toast";

import { type SupportRequest, supportApi } from "../api/supportApi";
import {
  ALLOWED_FILE_TYPES,
  FORM_VALIDATION,
  TOAST_MESSAGES,
} from "../constants/supportConstants";

export interface ContactFormData {
  type: string;
  title: string;
  description: string;
  attachments: File[];
}

export interface ContactSupportInitialValues {
  type?: string;
  title?: string;
  description?: string;
}

export function useContactSupport(initialValues?: ContactSupportInitialValues) {
  // Only the user's edits are stored. The form itself is derived during
  // render with `initialValues` as the source of truth, so a changed preset
  // is reflected immediately without a syncing effect (and its extra render).
  const [textEdits, setTextEdits] = useState<Partial<ContactFormData>>({});
  const [attachments, setAttachments] = useState<File[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // A new preset (fresh initialValues object) wipes edits + attachments —
  // master reset the whole form on preset change; ESC/backdrop closes fire
  // onOpenChange only, so the reset lives here, not in an effect.
  const [lastInitialValues, setLastInitialValues] = useState(initialValues);
  if (initialValues !== lastInitialValues) {
    setLastInitialValues(initialValues);
    setTextEdits({});
    setAttachments([]);
  }

  const formData: ContactFormData = {
    type: textEdits.type ?? initialValues?.type ?? "",
    title: textEdits.title ?? initialValues?.title ?? "",
    description: textEdits.description ?? initialValues?.description ?? "",
    attachments,
  };

  const handleInputChange = (
    field: "type" | "title" | "description",
    value: string,
  ) => {
    setTextEdits((prev) => {
      const next: Partial<ContactFormData> = { ...prev };
      next[field] = value;
      return next;
    });
  };

  const handleFileChange = (files: File[]) => {
    setAttachments(files);
  };

  const removeFile = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const resetForm = () => {
    setTextEdits({});
    setAttachments([]);
  };

  const validateForm = (): boolean => {
    if (!formData.type || !formData.title || !formData.description) {
      toast.error(TOAST_MESSAGES.VALIDATION_ERROR);
      return false;
    }

    if (formData.title.trim().length < FORM_VALIDATION.MIN_TITLE_LENGTH) {
      toast.error(TOAST_MESSAGES.TITLE_TOO_SHORT);
      return false;
    }

    if (
      formData.description.trim().length <
      FORM_VALIDATION.MIN_DESCRIPTION_LENGTH
    ) {
      toast.error(TOAST_MESSAGES.DESCRIPTION_TOO_SHORT);
      return false;
    }

    // Validate attachments
    if (formData.attachments.length > FORM_VALIDATION.MAX_ATTACHMENTS) {
      toast.error(`Maximum ${FORM_VALIDATION.MAX_ATTACHMENTS} images allowed`);
      return false;
    }

    // Validate individual files
    for (const file of formData.attachments) {
      if (file.size > FORM_VALIDATION.MAX_FILE_SIZE) {
        toast.error(
          `Image "${file.name}" exceeds maximum size of ${FORM_VALIDATION.MAX_FILE_SIZE / (1024 * 1024)}MB`,
        );
        return false;
      }

      if (
        !ALLOWED_FILE_TYPES.includes(
          file.type as (typeof ALLOWED_FILE_TYPES)[number],
        )
      ) {
        toast.error(`Only image files are supported for "${file.name}"`);
        return false;
      }
    }

    return true;
  };

  const submitRequest = async (): Promise<boolean> => {
    if (!validateForm()) {
      return false;
    }

    setIsSubmitting(true);

    try {
      const requestData: SupportRequest = {
        type: formData.type as "support" | "feature",
        title: formData.title.trim(),
        description: formData.description.trim(),
        attachments: formData.attachments,
      };

      const response = await supportApi.submitRequest(requestData);

      if (response.success) {
        const successMessage = response.ticket_id
          ? `${TOAST_MESSAGES.SUCCESS} Ticket ID: ${response.ticket_id}`
          : TOAST_MESSAGES.SUCCESS;
        toast.success(successMessage);
        resetForm();
        return true;
      } else {
        toast.error(response.message || TOAST_MESSAGES.GENERIC_ERROR);
        return false;
      }
    } catch (error) {
      console.error("Error submitting support request:", error);
      toast.error(TOAST_MESSAGES.GENERIC_ERROR);
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  const isFormValid = formData.type && formData.title && formData.description;

  return {
    formData,
    isSubmitting,
    isFormValid,
    handleInputChange,
    handleFileChange,
    removeFile,
    submitRequest,
    resetForm,
  };
}
