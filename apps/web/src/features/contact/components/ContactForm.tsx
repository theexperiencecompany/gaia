"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Turnstile } from "@marsidev/react-turnstile";
import type React from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  CONTACT_FORM_MESSAGES,
  TURNSTILE_SITE_KEY,
} from "@/features/contact/constants";
import { useVisitorContact } from "@/features/contact/hooks/useVisitorContact";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { SelfHostedSupportNotice } from "@/features/support/components/SelfHostedSupportNotice";
import {
  SUPPORT_REQUEST_TYPE_LABELS,
  SUPPORT_REQUEST_TYPES,
} from "@/features/support/constants/supportConstants";
import { useContactSupport } from "@/features/support/hooks/useContactSupport";

type Props = React.ComponentProps<"form"> & {
  initialType?: string;
  initialTitle?: string;
  initialDescription?: string;
};

export default function ContactForm(props: Props) {
  return useDeployment().gaia_support ? (
    <ContactRequestForm {...props} />
  ) : (
    <SelfHostedSupportNotice />
  );
}

function ContactRequestForm({
  initialType,
  initialTitle,
  initialDescription,
  ...formProps
}: Props) {
  const { formData, handleInputChange, isSubmitting, submitRequest } =
    useContactSupport({
      type: initialType,
      title: initialTitle,
      description: initialDescription,
    });
  // Only a sender with a session email goes through the signed-in route; anyone else proves they are human.
  const isVisitor = !useCurrentUser().email;
  const visitor = useVisitorContact();

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!isVisitor) {
      await submitRequest();
      return;
    }
    const contact = await visitor.verify();
    if (!contact) return;
    visitor.afterSubmit(await submitRequest(contact));
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-6" {...formProps}>
      {isVisitor && (
        <div className="grid gap-6 sm:grid-cols-2">
          <Input
            type="email"
            label="Email"
            placeholder="Where we should reply"
            value={visitor.email}
            onValueChange={visitor.setEmail}
            isInvalid={Boolean(visitor.emailError)}
            errorMessage={visitor.emailError}
            autoComplete="email"
            isRequired
          />
          <Input
            label="Name"
            placeholder="Optional"
            value={visitor.name}
            onValueChange={visitor.setName}
            maxLength={100}
            autoComplete="name"
          />
        </div>
      )}

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

      {isVisitor &&
        (TURNSTILE_SITE_KEY ? (
          <Turnstile
            ref={visitor.turnstileRef}
            siteKey={TURNSTILE_SITE_KEY}
            options={{ appearance: "interaction-only", theme: "dark" }}
            onError={visitor.onVerificationError}
            onSuccess={visitor.onVerified}
          />
        ) : (
          <p role="alert" className="text-sm text-danger">
            {CONTACT_FORM_MESSAGES.NOT_CONFIGURED}
          </p>
        ))}
      {isVisitor && visitor.verificationError && (
        <p role="alert" className="text-sm text-danger">
          {visitor.verificationError}
        </p>
      )}

      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={isSubmitting || (isVisitor && !TURNSTILE_SITE_KEY)}
          isLoading={visitor.isVerifying}
          color="primary"
        >
          {isSubmitting ? "Submitting..." : "Submit"}
        </Button>
      </div>
    </form>
  );
}
