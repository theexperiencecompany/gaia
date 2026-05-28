// Kapso / WhatsApp Cloud API webhook payload shapes.
//
// Meta's WhatsApp Cloud API ships inbound media as a typed object alongside the
// message envelope. Kapso passes these through verbatim (camelCase variants live
// under message.kapso.*; the raw Meta-shaped fields use snake_case mime_type —
// keep both optional so we stay tolerant to drift).

export interface WaMediaPayload {
  id?: string;
  link?: string;
  caption?: string;
  filename?: string;
  // Meta's Graph API field; both casings observed in the wild.
  mime_type?: string;
  mimeType?: string;
  sha256?: string;
  /** Voice-note flag set by WhatsApp on `audio` messages from push-to-talk. */
  voice?: boolean;
}

// Kapso v2 whatsapp.message.received event payload (single, non-batched).
// The event type is delivered via the X-Webhook-Event header, not in the body.
export interface KapsoMessageEvent {
  message: {
    id: string;
    timestamp: string;
    type: string; // "text" | "image" | "audio" | "voice" | "video" | "document" | "sticker" | ...
    text?: { body: string };
    image?: WaMediaPayload;
    audio?: WaMediaPayload;
    voice?: WaMediaPayload;
    video?: WaMediaPayload;
    document?: WaMediaPayload;
    sticker?: WaMediaPayload;
    kapso?: {
      direction: string;
      status: string;
      processing_status: string;
      origin: string;
      has_media: boolean;
      content?: string;
      // Kapso enrichments — present when fields=kapso(media_url) was set on
      // the original subscription. Lets us skip the Graph download round-trip.
      media_url?: string;
      mediaUrl?: string;
      media_data?: {
        url?: string;
        filename?: string;
        content_type?: string;
        contentType?: string;
        byte_size?: number;
        byteSize?: number;
      };
      mediaData?: {
        url?: string;
        filename?: string;
        contentType?: string;
        byteSize?: number;
      };
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

// Normalised media descriptor the adapter acts on, produced by extractMedia().
export interface ExtractedMedia {
  /**
   * Kind of media payload, mirroring `message.type` after `voice` is folded
   * into `audio`. Used to pick the right handler in the adapter.
   */
  kind: "image" | "audio" | "video" | "document" | "sticker";
  /** Whether this audio is a voice note (push-to-talk). Only meaningful for `kind === "audio"`. */
  isVoiceNote: boolean;
  /** WhatsApp media id used to download via the Cloud API. */
  mediaId: string;
  /** Best-known mime type, falling back to a sensible default per kind. */
  mimeType: string;
  /** Caption shipped alongside the media, if any. */
  caption?: string;
  /** Original filename for documents; absent for inline media. */
  filename?: string;
  /** Pre-resolved CDN URL when Kapso has already mirrored the media. */
  prefetchedUrl?: string;
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
