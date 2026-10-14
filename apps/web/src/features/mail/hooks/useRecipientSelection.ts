import { useState } from "react";
import { z } from "zod";
import { toast } from "@/lib/toast";

const emailValidationSchema = z.email("Invalid email address");

export type RecipientField = "to" | "cc" | "bcc";

export type RecipientMap = Record<RecipientField, string[]>;

export const RECIPIENT_FIELDS: {
  field: RecipientField;
  label: string;
  addLabel: string;
}[] = [
  { field: "to", label: "To", addLabel: "Add Recipients" },
  { field: "cc", label: "Cc", addLabel: "Add Cc" },
  { field: "bcc", label: "Bcc", addLabel: "Add Bcc" },
];

interface RecipientSeed {
  to?: string[];
  cc?: string[];
  bcc?: string[];
  /**
   * The addresses are already settled and the user cannot change them — a
   * stored draft, which is sent verbatim. An unsettled compose may propose
   * several candidates for the user to pick between.
   */
  isSettled: boolean;
}

function seedRecipients(seed: RecipientSeed): RecipientMap {
  const to = seed.to || [];
  return {
    to: seed.isSettled || to.length === 1 ? to : [],
    cc: seed.cc || [],
    bcc: seed.bcc || [],
  };
}

/**
 * Recipient selection for the compose card: the chosen addresses, the modal's
 * pending draft of them, and the suggestion chips (agent-resolved plus any the
 * user typed).
 */
export function useRecipientSelection(seed: RecipientSeed) {
  const [recipients, setRecipients] = useState<RecipientMap>(() =>
    seedRecipients(seed),
  );
  const [activeField, setActiveField] = useState<RecipientField | null>(null);

  // Draft copy of the active field's selection, edited inside the recipient
  // modal and committed to `recipients` only on confirm (Cancel discards it).
  const [draftEmails, setDraftEmails] = useState<string[]>([]);

  // Addresses added manually by the user, shown as suggestion chips alongside
  // the agent-provided ones.
  const [customSuggestions, setCustomSuggestions] = useState<RecipientMap>({
    to: [],
    cc: [],
    bcc: [],
  });

  const [customEmailInput, setCustomEmailInput] = useState("");
  const [customEmailError, setCustomEmailError] = useState("");

  // Derived instead of stored so they always follow the seed.
  const suggestions: RecipientMap = {
    to: [...(seed.to || []), ...customSuggestions.to],
    cc: [...(seed.cc || []), ...customSuggestions.cc],
    bcc: [...(seed.bcc || []), ...customSuggestions.bcc],
  };

  const openField = (field: RecipientField) => {
    setCustomEmailInput("");
    setCustomEmailError("");
    setDraftEmails(recipients[field]);
    setActiveField(field);
  };

  const closeField = () => setActiveField(null);

  // Commit the modal's draft selection back to the active field, then close.
  const commitDraft = () => {
    if (activeField) {
      setRecipients((prev) => ({ ...prev, [activeField]: draftEmails }));
    }
    setActiveField(null);
  };

  const validateCustomEmail = (email: string): boolean => {
    try {
      emailValidationSchema.parse(email);
      setCustomEmailError("");
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        setCustomEmailError(error.issues[0]?.message || "Invalid email");
      }
      return false;
    }
  };

  // Add a manually typed email to the active field's draft selection.
  const addCustomEmail = () => {
    if (!activeField) return;

    const trimmedEmail = customEmailInput.trim();

    if (!trimmedEmail) {
      setCustomEmailError("Please enter an email address");
      return;
    }

    if (!validateCustomEmail(trimmedEmail)) {
      return;
    }

    if (draftEmails.includes(trimmedEmail)) {
      setCustomEmailError("Email already added");
      return;
    }

    setDraftEmails((prev) => [...prev, trimmedEmail]);

    if (!suggestions[activeField].includes(trimmedEmail)) {
      const field = activeField;
      setCustomSuggestions((prev) => ({
        ...prev,
        [field]: [...prev[field], trimmedEmail],
      }));
    }

    setCustomEmailInput("");
    setCustomEmailError("");
    toast.success(`Added ${trimmedEmail}`);
  };

  return {
    recipients,
    activeField,
    activeFieldConfig: RECIPIENT_FIELDS.find((f) => f.field === activeField),
    activeSuggestions: activeField ? suggestions[activeField] : [],
    draftEmails,
    setDraftEmails,
    customEmailInput,
    setCustomEmailInput,
    customEmailError,
    setCustomEmailError,
    openField,
    closeField,
    commitDraft,
    addCustomEmail,
  };
}
