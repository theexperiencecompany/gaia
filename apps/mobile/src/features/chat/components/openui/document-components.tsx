/**
 * Document components — re-exported from the OpenUI config layer.
 *
 * The implementations live in:
 *   apps/mobile/src/config/openui/components/document.tsx
 *
 * Mobile-specific behaviour:
 * - TextDocument uses MarkdownRenderer (react-native-markdown-display) instead
 *   of Tiptap, which is web-only. The body field accepts raw markdown or HTML.
 * - Metadata fields render as InnerCard label/value pairs.
 * - Copy functionality is omitted on mobile; the share sheet handles this natively.
 */
export {
  TextDocumentView,
  textDocumentDef,
  textDocumentSchema,
} from "@/config/openui/components/document";
