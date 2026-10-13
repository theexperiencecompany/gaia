import type { EventProperties } from "@gaia/shared/analytics/events";

export type ShareChannel = EventProperties["referral:share_clicked"]["channel"];

/** Where an invite code lives on the site; the API builds share links on the same path. */
export const INVITE_PATH = "/invite/";

/** The channels that open another app; native, copy and QR are handled in place. */
export type LinkChannel = Extract<
  ShareChannel,
  "whatsapp" | "sms" | "x" | "linkedin" | "email"
>;

export const LINK_CHANNELS: readonly LinkChannel[] = [
  "whatsapp",
  "sms",
  "x",
  "linkedin",
  "email",
];

interface ShareMessage {
  text: string;
  url: string;
  emailSubject: string;
}

/** iOS reads the body after "&", Android after "?"; the wrong one opens an empty message. */
function smsHref(body: string, userAgent: string): string {
  const separator = /iPad|iPhone|iPod|Macintosh/.test(userAgent) ? "&" : "?";
  return `sms:${separator}body=${encodeURIComponent(body)}`;
}

export function channelHref(
  channel: LinkChannel,
  { text, url, emailSubject }: ShareMessage,
  userAgent: string,
): string {
  const withLink = `${text} ${url}`;
  switch (channel) {
    case "whatsapp":
      return `https://wa.me/?text=${encodeURIComponent(withLink)}`;
    case "sms":
      return smsHref(withLink, userAgent);
    case "x":
      return `https://x.com/intent/post?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
    case "linkedin":
      return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`;
    case "email":
      return `mailto:?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(withLink)}`;
  }
}
