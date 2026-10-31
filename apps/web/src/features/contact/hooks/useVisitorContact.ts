"use client";

import type { TurnstileInstance } from "@marsidev/react-turnstile";
import { useRef, useState } from "react";
import { z } from "zod";

import type { VisitorContact } from "@/features/support/hooks/useContactSupport";

import { CONTACT_FORM_MESSAGES } from "../constants";

const emailSchema = z.email();

/** The inline error for an email field value, or null when it is a valid address. */
function validateEmail(value: string): string | null {
  return emailSchema.safeParse(value.trim()).success
    ? null
    : CONTACT_FORM_MESSAGES.INVALID_EMAIL;
}

/** The reply address, optional name and Turnstile proof a sender without a session email supplies. */
export function useVisitorContact() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [verificationError, setVerificationError] = useState<string | null>(
    null,
  );
  const [isVerifying, setIsVerifying] = useState(false);
  const turnstileRef = useRef<TurnstileInstance>(null);

  /** Validate the email and wait for a Turnstile token; null (with the reason shown) when either fails. */
  const verify = async (): Promise<VisitorContact | null> => {
    // The field's own validation blocks the submit first; this guards a programmatic one.
    if (validateEmail(email)) return null;

    const turnstile = turnstileRef.current;
    if (!turnstile) {
      setVerificationError(CONTACT_FORM_MESSAGES.NOT_CONFIGURED);
      return null;
    }

    setIsVerifying(true);
    try {
      const turnstileToken = await turnstile.getResponsePromise();
      setVerificationError(null);
      return {
        email: email.trim(),
        name: name.trim(),
        turnstile_token: turnstileToken,
      };
    } catch (error) {
      console.error("Turnstile did not produce a token:", error);
      setVerificationError(CONTACT_FORM_MESSAGES.VERIFICATION_FAILED);
      return null;
    } finally {
      setIsVerifying(false);
    }
  };

  /** Tokens are single-use: fetch a fresh one after every submit, and clear the fields once it landed. */
  const afterSubmit = (submitted: boolean) => {
    turnstileRef.current?.reset();
    if (!submitted) return;
    setEmail("");
    setName("");
  };

  return {
    email,
    setEmail,
    name,
    setName,
    validateEmail,
    verificationError,
    onVerificationError: () =>
      setVerificationError(CONTACT_FORM_MESSAGES.VERIFICATION_FAILED),
    onVerified: () => setVerificationError(null),
    isVerifying,
    turnstileRef,
    verify,
    afterSubmit,
  };
}
