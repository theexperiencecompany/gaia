"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import type React from "react";

import {
  SUPPORT_REQUEST_TYPE_LABELS,
  SUPPORT_REQUEST_TYPES,
} from "@/features/support/constants/supportConstants";
import { useContactSupport } from "@/features/support/hooks/useContactSupport";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

type Props = React.ComponentProps<"form">;

export default function ContactForm(props: Props) {
  const { formData, handleInputChange, isSubmitting, submitRequest } =
    useContactSupport();

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();

    trackEvent(ANALYTICS_EVENTS.SUPPORT_FORM_SUBMITTED, {
      request_type: formData.type,
      title_length: formData.title.length,
      description_length: formData.description.length,
    });

    await submitRequest();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-6" {...props}>
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
        maxLength={200}
        isRequired
      />

      <Textarea
        label="Description"
        placeholder="Please provide detailed information about your request..."
        value={formData.description}
        onValueChange={(value) => handleInputChange("description", value)}
        minRows={4}
        maxRows={10}
        maxLength={2000}
        isRequired
      />

      <div className="flex justify-end">
        <Button type="submit" disabled={isSubmitting} color="primary">
          {isSubmitting ? "Submitting..." : "Submit"}
        </Button>
      </div>
    </form>
  );
}
