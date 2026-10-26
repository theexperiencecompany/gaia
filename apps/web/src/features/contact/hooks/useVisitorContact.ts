"use client";

import type { TurnstileInstance } from "@marsidev/react-turnstile";
import { useRef, useState } from "react";
import { z } from "zod";

import type { VisitorContact } from "@/features/support/hooks/useContactSupport";

import { CONTACT_FORM_MESSAGES } from "../constants";

const emailSchema = z.email();

/** The reply address, optional name and Turnstile proof a sender without a session email supplies. */
export function useVisitorContact() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(
    null,
  );
  const [isVerifying, setIsVerifying] = useState(false);
  const turnstileRef = useRef<TurnstileInstance>(null);

  const emailIsValid = emailSchema.safeParse(email.trim()).success;

  /** Validate the email and wait for a Turnstile token; null (with the reason shown) when either fails. */
  const verify = async (): Promise<VisitorContact | null> => {
    setEmailTouched(true);
    if (!emailIsValid) return null;

    const turnstile = turnstileRef.current;
    if (!turnstile) {
      setVerificationError(CONTACT_FORM_MESSAGES.NOT_CONFIGURED);
      return null;
    }

    setIsVerifying(true);
    try {
      const turnstileToken = await turnstile.getResponsePromise();
      setVerificationError(null);
      return { email: email.trim(), name: name.trim(), turnstileToken };
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
    setEmailTouched(false);
  };

  return {
    email,
    setEmail,
    name,
    setName,
    emailError:
      emailTouched && !emailIsValid
        ? CONTACT_FORM_MESSAGES.INVALID_EMAIL
        : undefined,
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
