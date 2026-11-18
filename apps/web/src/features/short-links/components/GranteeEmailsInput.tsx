"use client";

import {
  Description,
  FieldError,
  Input,
  Label,
  Tag,
  TagGroup,
  TextField,
} from "@heroui/react";
import { type KeyboardEvent, useState } from "react";
import { z } from "zod";

import { LINK_CONSTANTS } from "@/features/short-links/link-constants.generated";

const emailSchema = z.email();
const SEPARATOR_KEYS = new Set(["Enter", ","]);

interface GranteeEmailsInputProps {
  emails: string[];
  onEmailsChange: (emails: string[]) => void;
  /** Saving was tried with no one listed. */
  isMissing: boolean;
}

/** The emails a "Specific people" link opens for: typed, added with Enter or a comma, removed as chips. */
export function GranteeEmailsInput({
  emails,
  onEmailsChange,
  isMissing,
}: GranteeEmailsInputProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const commit = () => {
    const email = draft.trim().toLowerCase();
    if (!email) return;
    if (!emailSchema.safeParse(email).success) {
      setError("Enter a valid email address.");
      return;
    }
    if (!emails.includes(email)) {
      if (emails.length >= LINK_CONSTANTS.maxGrantees) {
        setError(
          `You can share with up to ${LINK_CONSTANTS.maxGrantees} people.`,
        );
        return;
      }
      onEmailsChange([...emails, email]);
    }
    setDraft("");
    setError(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!SEPARATOR_KEYS.has(event.key)) return;
    event.preventDefault();
    commit();
  };

  const shownError =
    error ?? (isMissing ? "Add at least one email address." : null);

  return (
    <div className="flex flex-col gap-2">
      <TextField
        type="email"
        value={draft}
        onChange={(value) => {
          setDraft(value);
          setError(null);
        }}
        onKeyDown={onKeyDown}
        onBlur={commit}
        isInvalid={shownError !== null}
      >
        <Label>People</Label>
        <Input placeholder="name@example.com" />
        {shownError ? (
          <FieldError>{shownError}</FieldError>
        ) : (
          <Description>
            Press Enter or a comma after each email. They open it signed in to
            GAIA with that email.
          </Description>
        )}
      </TextField>
      {emails.length > 0 && (
        <TagGroup
          aria-label="People with access"
          size="sm"
          onRemove={(removed) =>
            onEmailsChange(emails.filter((email) => !removed.has(email)))
          }
        >
          <TagGroup.List>
            {emails.map((email) => (
              <Tag key={email} id={email} textValue={email}>
                {email}
                <Tag.RemoveButton aria-label={`Remove ${email}`} />
              </Tag>
            ))}
          </TagGroup.List>
        </TagGroup>
      )}
    </div>
  );
}
