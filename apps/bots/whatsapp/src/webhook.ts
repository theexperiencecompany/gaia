import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Verifies a Kapso webhook signature.
 *
 * Kapso signs the raw request body with HMAC-SHA256 using your webhook secret.
 * The signature is provided in the X-Kapso-Signature header as "sha256=<hex>".
 */
export function verifyKapsoSignature(
  rawBody: string,
  signatureHeader: string | null,
  secret: string,
): boolean {
  if (!signatureHeader) return false;
  const expected = `sha256=${createHmac("sha256", secret)
    .update(rawBody, "utf8")
    .digest("hex")}`;
  try {
    return timingSafeEqual(Buffer.from(signatureHeader), Buffer.from(expected));
  } catch {
    return false;
  }
}

/**
 * Extracts the WhatsApp phone number (wa_id) from a Kapso message.received event.
 * wa_id is the sender's phone number without the leading '+', e.g. "15551234567".
 */
export function extractWaId(event: KapsoMessageEvent): string {
  return event.data.from;
}

/**
 * Extracts the text body from a Kapso text message event.
 * Returns null if the message is not a text message.
 */
export function extractTextBody(event: KapsoMessageEvent): string | null {
  if (event.data.type !== "text") return null;
  return event.data.text?.body ?? null;
}

// Minimal type for Kapso whatsapp.message.received event (v2 payload)
export interface KapsoMessageEvent {
  type: string; // "whatsapp.message.received"
  data: {
    id: string;
    from: string; // wa_id (phone number without +)
    type: string; // "text" | "image" | "audio" | "document" | ...
    timestamp: string;
    text?: { body: string };
    phone_number_id: string;
  };
}
