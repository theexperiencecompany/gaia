import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Verifies a Kapso webhook signature.
 *
 * Kapso signs the raw request body with HMAC-SHA256 using your webhook secret.
 * The signature is provided in the X-Webhook-Signature header as a raw hex string
 * (no prefix).
 */
export function verifyKapsoSignature(
  rawBody: string,
  signatureHeader: string | null,
  secret: string,
): boolean {
  if (!signatureHeader) return false;
  const expected = createHmac("sha256", secret)
    .update(rawBody, "utf8")
    .digest("hex");
  try {
    return timingSafeEqual(Buffer.from(signatureHeader), Buffer.from(expected));
  } catch {
    return false;
  }
}

/**
 * Extracts the WhatsApp phone number (wa_id) from a Kapso message.received event.
 * wa_id is the sender's phone number without the leading '+', e.g. "15551234567".
 * Kapso provides conversation.phone_number with a leading '+'.
 */
export function extractWaId(event: KapsoMessageEvent): string {
  return event.conversation.phone_number.replace(/^\+/, "");
}

/**
 * Extracts the text body from a Kapso text message event.
 * Returns null if the message is not a text message.
 */
export function extractTextBody(event: KapsoMessageEvent): string | null {
  if (event.message.type !== "text") return null;
  return event.message.text?.body ?? null;
}

// Kapso v2 whatsapp.message.received event payload (single, non-batched).
// The event type is delivered via the X-Webhook-Event header, not in the body.
export interface KapsoMessageEvent {
  message: {
    id: string;
    timestamp: string;
    type: string; // "text" | "image" | "audio" | "document" | ...
    text?: { body: string };
    kapso?: {
      direction: string;
      status: string;
      processing_status: string;
      origin: string;
      has_media: boolean;
      content?: string;
    };
  };
  conversation: {
    id: string;
    phone_number: string; // e.g. "+15551234567" — WITH leading "+"
    phone_number_id: string;
    status: string;
  };
  is_new_conversation?: boolean;
  phone_number_id: string;
}

// Batched variant: Kapso wraps multiple events in a data array.
// Present when X-Webhook-Batch: true is set on the request.
export interface KapsoMessageBatch {
  type: string; // "whatsapp.message.received"
  batch: true;
  data: KapsoMessageEvent[];
  batch_info: {
    size: number;
    window_ms: number;
    first_sequence: number;
    last_sequence: number;
    conversation_id: string;
  };
}
