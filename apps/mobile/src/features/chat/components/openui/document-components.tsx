/**
 * Document components re-exported from
 * apps/mobile/src/config/openui/components/document.tsx. TextDocument uses
 * MarkdownRenderer instead of the web-only Tiptap (body accepts raw markdown or
 * HTML); metadata renders as InnerCard label/value pairs; copy is omitted since
 * the share sheet handles it natively.
 */
export {
  TextDocumentView,
  textDocumentDef,
  textDocumentSchema,
} from "@/config/openui/components/document";
