"use client";

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { type KeyboardEvent, useState } from "react";
import { z } from "zod";

import { MAX_GRANTEES } from "@/features/short-links/constants";

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
      if (emails.length >= MAX_GRANTEES) {
        setError(`You can share with up to ${MAX_GRANTEES} people.`);
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
      <Input
        label="People"
        labelPlacement="outside"
        placeholder="name@example.com"
        type="email"
        value={draft}
        onValueChange={(value) => {
          setDraft(value);
          setError(null);
        }}
        onKeyDown={onKeyDown}
        onBlur={commit}
        isInvalid={shownError !== null}
        errorMessage={shownError}
        description="Press Enter or a comma after each email. They open it signed in to GAIA with that email."
      />
      {emails.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {emails.map((email) => (
            <Chip
              key={email}
              size="sm"
              variant="flat"
              onClose={() => onEmailsChange(emails.filter((e) => e !== email))}
            >
              {email}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}
