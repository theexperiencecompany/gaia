"use client";

import { useState } from "react";
import { toast } from "sonner";

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
  const [formData, setFormData] = useState<ContactFormData>({
    type: initialValues?.type || "",
    title: initialValues?.title || "",
    description: initialValues?.description || "",
    attachments: [],
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleInputChange = (field: keyof ContactFormData, value: string) => {
    setFormData((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleFileChange = (files: File[]) => {
    setFormData((prev) => ({
      ...prev,
      attachments: files,
    }));
  };

  const removeFile = (index: number) => {
    setFormData((prev) => ({
      ...prev,
      attachments: prev.attachments.filter((_, i) => i !== index),
    }));
  };

  const resetForm = () => {
    setFormData({
      type: "",
      title: "",
      description: "",
      attachments: [],
    });
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
