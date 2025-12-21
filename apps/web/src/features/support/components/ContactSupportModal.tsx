"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Select, SelectItem } from "@heroui/select";
import Image from "next/image";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Cancel01Icon, Upload01Icon } from "@/icons";

import {
  ALLOWED_FILE_TYPES,
  FORM_VALIDATION,
  SUPPORT_REQUEST_TYPE_LABELS,
  SUPPORT_REQUEST_TYPES,
} from "../constants/supportConstants";
import { useContactSupport } from "../hooks/useContactSupport";

interface ContactSupportModalProps {
  isOpen: boolean;
  onOpenChange: () => void;
  initialValues?: {
    type?: string;
    title?: string;
    description?: string;
  };
}

export default function ContactSupportModal({
  isOpen,
  onOpenChange,
  initialValues,
}: ContactSupportModalProps) {
  const {
    formData,
    isSubmitting,
    isFormValid,
    handleInputChange,
    handleFileChange,
    removeFile,
    submitRequest,
    resetForm,
  } = useContactSupport(initialValues);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const validateFile = (file: File): boolean => {
    // Check file type - only images allowed
    if (
      !ALLOWED_FILE_TYPES.includes(
        file.type as (typeof ALLOWED_FILE_TYPES)[number],
      )
    ) {
      toast.error(
        `Only image files are supported. Please use: JPG, PNG, or WebP`,
      );
      return false;
    }

    // Check file size
    if (file.size > FORM_VALIDATION.MAX_FILE_SIZE) {
      toast.error(
        `Image size too large. Maximum size is ${FORM_VALIDATION.MAX_FILE_SIZE / (1024 * 1024)}MB`,
      );
      return false;
    }

    return true;
  };

  const handleFiles = (files: FileList | null) => {
    if (!files) return;

    const currentAttachments = formData.attachments.length;
    const newFiles = Array.from(files);

    // Check total attachment limit
    if (
      currentAttachments + newFiles.length >
      FORM_VALIDATION.MAX_ATTACHMENTS
    ) {
      toast.error(`Maximum ${FORM_VALIDATION.MAX_ATTACHMENTS} images allowed`);
      return;
    }

    // Validate each file
    const validFiles = newFiles.filter(validateFile);

    if (validFiles.length > 0) {
      handleFileChange([...formData.attachments, ...validFiles]);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files);
    // Reset input value to allow selecting the same file again
    e.target.value = "";
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
  };

  const handleSubmit = async () => {
    const success = await submitRequest();
    if (success) {
      onOpenChange();
    }
  };

  const handleClose = () => {
    resetForm();
    onOpenChange();
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="2xl"
      backdrop="blur"
      isDismissable={false}
    >
      <ModalContent>
        {() => (
          <>
            <ModalHeader className="flex flex-col gap-1">
              Get in Touch
            </ModalHeader>

            <ModalBody className="gap-4">
              <Select
                label="Request Type"
                placeholder="Select a request type"
                selectedKeys={formData.type ? [formData.type] : []}
                onSelectionChange={(keys) => {
                  const selectedKey = Array.from(keys)[0] as string;
                  handleInputChange("type", selectedKey);
                }}
                isRequired
              >
                <SelectItem key={SUPPORT_REQUEST_TYPES.SUPPORT}>
                  {SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.SUPPORT]}
                </SelectItem>
                <SelectItem key={SUPPORT_REQUEST_TYPES.FEATURE}>
                  {SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.FEATURE]}
                </SelectItem>
              </Select>

              <Input
                label="Title"
                placeholder="Brief description of your request"
                value={formData.title}
                onValueChange={(value) => handleInputChange("title", value)}
                maxLength={FORM_VALIDATION.MAX_TITLE_LENGTH}
                isRequired
              />

              <Textarea
                label="Description"
                placeholder="Please provide detailed information about your request..."
                value={formData.description}
                onValueChange={(value) =>
                  handleInputChange("description", value)
                }
                minRows={4}
                maxRows={10}
                maxLength={FORM_VALIDATION.MAX_DESCRIPTION_LENGTH}
                isRequired
              />

              {/* File Upload01Icon Section */}
              <div className="space-y-3">
                {/* Upload01Icon Area - Entire area is clickable */}
                <div
                  className={`cursor-pointer rounded-2xl border-2 border-dashed p-5 text-center transition-all duration-200 ${
                    dragActive
                      ? "scale-[1.02] border-primary bg-blue-50 shadow-lg"
                      : "hover:bg-zinc-750 border-zinc-700 bg-zinc-800 hover:border-primary"
                  }`}
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept={ALLOWED_FILE_TYPES.join(",")}
                    onChange={handleFileInputChange}
                    className="hidden"
                  />

                  <div className="flex flex-col items-center space-y-2">
                    <div
                      className={`rounded-full p-4 ${dragActive ? "bg-blue-100" : "bg-zinc-700"} transition-colors`}
                    >
                      <Upload01Icon
                        className={`h-8 w-8 ${dragActive ? "text-blue-600" : "text-gray-400"} transition-colors`}
                      />
                    </div>

                    <div className="space-y-1">
                      <p
                        className={`font-medium ${dragActive ? "text-blue-600" : "text-zinc-200"} transition-colors`}
                      >
                        {dragActive
                          ? "Drop your images here"
                          : "Upload Images (Optional)"}
                      </p>
                      <p className="text-sm text-zinc-400">
                        {dragActive
                          ? "Release to upload"
                          : "Click here or drag & drop your images"}
                      </p>
                    </div>

                    <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-zinc-400">
                      <span className="rounded-full bg-zinc-700 px-3 py-1">
                        Max {FORM_VALIDATION.MAX_ATTACHMENTS} images
                      </span>
                      <span className="rounded-full bg-zinc-700 px-3 py-1">
                        Up to {FORM_VALIDATION.MAX_FILE_SIZE / (1024 * 1024)}MB
                        each
                      </span>
                      <span className="rounded-full bg-zinc-700 px-3 py-1">
                        JPG, PNG, WebP
                      </span>
                    </div>
                  </div>
                </div>

                {/* File List */}
                {formData.attachments.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-sm font-medium text-zinc-300">
                      Attached Images ({formData.attachments.length}/
                      {FORM_VALIDATION.MAX_ATTACHMENTS})
                    </p>
                    <div className="grid grid-cols-5 gap-3">
                      {formData.attachments.map((file, index) => (
                        <div
                          key={file.name + file.size}
                          className="group relative overflow-hidden rounded-xl bg-zinc-800"
                        >
                          <div className="aspect-square">
                            <Image
                              src={URL.createObjectURL(file)}
                              alt={file.name}
                              fill
                              className="object-cover transition-transform group-hover:scale-105"
                            />
                          </div>

                          {/* Overlay with file info */}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100">
                            <div className="absolute right-2 bottom-2 left-2">
                              <p className="truncate text-xs font-medium text-white">
                                {file.name}
                              </p>
                              <p className="text-xs text-zinc-300">
                                {formatFileSize(file.size)}
                              </p>
                            </div>
                          </div>

                          {/* Remove button */}
                          <button
                            type="button"
                            onClick={() => removeFile(index)}
                            className="absolute top-2 right-2 rounded-full bg-red-500 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-600"
                          >
                            <Cancel01Icon className="h-3 w-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </ModalBody>
            <ModalFooter>
              <Button color="danger" variant="light" onPress={handleClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={handleSubmit}
                isLoading={isSubmitting}
                isDisabled={!isFormValid}
              >
                Submit Request
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
