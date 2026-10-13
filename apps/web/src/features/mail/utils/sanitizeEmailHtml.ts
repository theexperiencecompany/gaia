import DOMPurify from "dompurify";

/** Sanitize third-party email HTML for in-app rendering; links keep `target` so they open in a new tab. */
export function sanitizeEmailHtml(html: string): string {
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
}
