"use client";

import {
  Button,
  FieldError,
  Input,
  Label,
  ListBox,
  Select,
  TextArea,
  TextField,
} from "@heroui/react";
import { Turnstile } from "@marsidev/react-turnstile";
import type React from "react";
import { fieldVariants } from "@/components/shared/fieldVariants";
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
          <TextField
            className={fieldVariants({ labelPlacement: "inside" })}
            type="email"
            value={visitor.email}
            onChange={visitor.setEmail}
            validate={visitor.validateEmail}
            isRequired
          >
            <Label>Email</Label>
            <Input placeholder="Where we should reply" autoComplete="email" />
            <FieldError />
          </TextField>
          <TextField
            className={fieldVariants({ labelPlacement: "inside" })}
            value={visitor.name}
            onChange={visitor.setName}
          >
            <Label>Name</Label>
            <Input placeholder="Optional" maxLength={100} autoComplete="name" />
          </TextField>
        </div>
      )}

      <Select
        className={fieldVariants({ labelPlacement: "inside" })}
        placeholder="Select a request type"
        selectedKey={formData.type ?? null}
        onSelectionChange={(key) => {
          handleInputChange("type", key as string);
        }}
        isRequired
      >
        <Label>Request Type</Label>
        <Select.Trigger>
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            <ListBox.Item
              id={SUPPORT_REQUEST_TYPES.SUPPORT}
              textValue={
                SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.SUPPORT]
              }
            >
              {SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.SUPPORT]}
            </ListBox.Item>
            <ListBox.Item
              id={SUPPORT_REQUEST_TYPES.FEATURE}
              textValue={
                SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.FEATURE]
              }
            >
              {SUPPORT_REQUEST_TYPE_LABELS[SUPPORT_REQUEST_TYPES.FEATURE]}
            </ListBox.Item>
          </ListBox>
        </Select.Popover>
      </Select>

      <TextField
        className={fieldVariants({ labelPlacement: "inside" })}
        value={formData.title}
        onChange={(value) => handleInputChange("title", value)}
        isRequired
      >
        <Label>Title</Label>
        <Input
          placeholder="Brief description of your request"
          maxLength={200}
        />
      </TextField>

      <TextField
        className={fieldVariants({ labelPlacement: "inside" })}
        value={formData.description}
        onChange={(value) => handleInputChange("description", value)}
        isRequired
      >
        <Label>Description</Label>
        <TextArea
          placeholder="Please provide detailed information about your request..."
          maxLength={2000}
          className="field-sizing-content min-h-[4lh] max-h-[10lh]"
        />
      </TextField>

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
          isDisabled={isSubmitting || (isVisitor && !TURNSTILE_SITE_KEY)}
          isPending={visitor.isVerifying}
          variant="primary"
        >
          {isSubmitting ? "Submitting..." : "Submit"}
        </Button>
      </div>
    </form>
  );
}
