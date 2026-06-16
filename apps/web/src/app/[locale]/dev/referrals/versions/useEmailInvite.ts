"use client";

import { type KeyboardEvent, useState } from "react";

import { toast } from "@/lib/toast";

import { parseEmails } from "./mockData";

/** Shared email-invite field behavior. The page renders its own input +
 *  button; only the parse/validate/toast flow is shared. Mock-only, no
 *  network call. On send it fires a success toast and clears the input; on
 *  empty/invalid input it fires an error toast. */
export function useEmailInvite(
  successCopy?: (count: number, emails: string[]) => string,
) {
  const [email, setEmail] = useState("");

  const send = () => {
    const valid = parseEmails(email);
    if (valid.length === 0) {
      toast.error("Enter at least one valid email address");
      return;
    }
    toast.success(
      successCopy
        ? successCopy(valid.length, valid)
        : `Invite sent to ${valid.length} friend${valid.length > 1 ? "s" : ""}`,
    );
    setEmail("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      send();
    }
  };

  return { email, setEmail, send, onKeyDown };
}
