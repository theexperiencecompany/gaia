/**
 * Wire contract for messages the backend publishes to a platform's outbound
 * queue. Mirrors ``apps/api/app/schemas/outbound.py``.
 *
 * The consumer validates each message against this schema at the queue boundary
 * so a malformed or renamed payload is rejected to the DLQ with a clear reason,
 * rather than failing deep in the platform send path with an undefined field.
 *
 * The schema is the single source of truth; consumers derive the static type via
 * ``z.infer<typeof outboundMessageEnvelopeSchema>`` so runtime validation and the
 * static type cannot drift apart.
 */

import { z } from "zod";

/**
 * A file the bot should deliver. Bytes are NOT inlined — the bot fetches them
 * itself, either from the backend artifact store (bot-authenticated) via
 * `conversation_id`/`path`, or directly from a CDN `url` (e.g. a signed
 * browser-automation step screenshot) — exactly one source is set.
 */
export const outboundAttachmentSchema = z
  .object({
    conversation_id: z.string().min(1).nullish(),
    /**
     * Artifact path relative to the session's artifacts/ dir. Rejected at the
     * queue boundary if absolute or containing a `..` segment, so a malformed
     * envelope can't turn into arbitrary-file access in the artifact fetch.
     */
    path: z
      .string()
      .min(1)
      .refine((p) => !p.startsWith("/") && !p.split("/").includes(".."), {
        message: "path must be relative to artifacts/ (no leading '/' or '..')",
      })
      .nullish(),
    /** CDN source; fetched directly, no GAIA auth involved. */
    url: z
      .string()
      .refine((u) => u.startsWith("http://") || u.startsWith("https://"), {
        message: "url must be an http(s) URL",
      })
      .nullish(),
    filename: z.string().min(1),
    content_type: z.string().nullish(),
    caption: z.string().nullish(),
  })
  .refine((a) => Boolean(a.url) !== Boolean(a.conversation_id && a.path), {
    message:
      "attachment requires exactly one of `url` or (`conversation_id` + `path`)",
  });

export const outboundMessageEnvelopeSchema = z
  .object({
    /** Unique id (idempotency + tracing). */
    id: z.string().min(1),
    /** Target platform — informational; each queue is already platform-specific. */
    platform: z.string().min(1),
    /** Platform-native destination id (wa_id, Discord/Telegram/Slack user id). */
    destination_id: z.string().min(1),
    /** Raw CommonMark message body. Optional when an attachment is present. */
    text: z.string().min(1).nullish(),
    /**
     * Ordered CommonMark bubbles delivered as ONE message. The consumer sends
     * them sequentially so their order is preserved — used for multi-bubble
     * notifications (e.g. a workflow completion: header, results, footer) that
     * would otherwise race each other if published as separate envelopes.
     */
    text_parts: z.array(z.string()).nullish(),
    /** A file to deliver (PDF/docx/etc.) — optional. */
    attachment: outboundAttachmentSchema.nullish(),
    /** ISO-8601 enqueue timestamp. */
    enqueued_at: z.string(),
  })
  .refine(
    (e) =>
      Boolean(e.text) || Boolean(e.text_parts?.length) || Boolean(e.attachment),
    { message: "envelope requires text, text_parts, or attachment" },
  );

export type OutboundAttachment = z.infer<typeof outboundAttachmentSchema>;
export type OutboundMessageEnvelope = z.infer<
  typeof outboundMessageEnvelopeSchema
>;
