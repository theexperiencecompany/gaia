/**
 * Node-safe single source of truth for the GAIA-only OpenUI component schemas.
 *
 * This module imports ONLY `zod` — no `@/` aliases, no React, no browser deps —
 * so it can be imported both by the React component files (which add the views)
 * AND by the Node prompt generator (`scripts/openui/generate-prompt.ts`).
 *
 * Each component file re-exports its schema from here and supplies the view +
 * `defineComponent` call. The backend LLM prompt's component vocabulary is
 * generated from `GAIA_COMPONENT_SPECS` merged with `@openuidev/react-ui`'s
 * library — keeping the prompt and the renderer in lockstep.
 */
import { z } from "zod";

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export const gaugeChartSchema = z.object({
  value: z.number(),
  title: z.string().optional(),
  min: z.number().optional(),
  max: z.number().optional(),
  unit: z.string().optional(),
  thresholds: z.object({ warning: z.number(), danger: z.number() }).optional(),
  variant: z.enum(["gauge", "text", "stacked"]).optional(),
  secondValue: z.number().optional(),
  secondLabel: z.string().optional(),
  size: z.enum(["sm", "md", "lg"]).optional(),
});

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

export const imageGallerySchema = z.object({
  images: z.array(
    z.object({
      src: z.string(),
      alt: z.string().optional(),
      caption: z.string().optional(),
    }),
  ),
  columns: z.number().int().min(1).max(6).optional(),
  gap: z.enum(["xs", "sm", "md", "lg"]).optional(),
  aspectRatio: z.string().optional(),
  maxWidth: z.enum(["sm", "md", "lg", "xl", "full"]).optional(),
});

export const videoBlockSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  poster: z.string().optional(),
});

export const audioPlayerSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
});

const mapPointSchema = z.object({
  lat: z.number(),
  lng: z.number(),
});

const mapMarkerSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  popup: z.string().optional(),
  tooltip: z.string().optional(),
});

const mapRouteItemSchema = z.object({
  points: z.array(mapPointSchema),
  color: z.string().optional(),
  width: z.number().optional(),
  opacity: z.number().optional(),
  dashArray: z.tuple([z.number(), z.number()]).optional(),
});

const mapArcItemSchema = z.object({
  id: z.union([z.string(), z.number()]).optional(),
  from: mapPointSchema,
  to: mapPointSchema,
  label: z.string().optional(),
});

export const mapBlockSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  zoom: z.number().optional(),
  markers: z.array(mapMarkerSchema).optional(),
  routes: z.array(mapRouteItemSchema).optional(),
  arcs: z.array(mapArcItemSchema).optional(),
  fitBounds: z.boolean().optional(),
});

export const numberTickerSchema = z.object({
  value: z.number(),
  label: z.string().optional(),
  unit: z.string().optional(),
  duration: z.number().optional(),
  size: z.enum(["sm", "md", "lg"]).optional(),
});

// ---------------------------------------------------------------------------
// Layout & data
// ---------------------------------------------------------------------------

export const copyableContentSchema = z.object({
  content: z.string(),
  mode: z.enum(["inline", "block"]).optional(),
  languageHint: z.string().optional(),
});

export const fileTreeSchema = z.object({
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir", "item"]).optional(),
      size: z.string().optional(),
      description: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
  variant: z.enum(["file", "generic"]).optional(),
});

export const kbdRowSchema = z.object({
  keys: z.array(z.string()),
  description: z.string().optional(),
});

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

export const progressSchema = z.object({
  value: z.number(),
  max: z.number().optional(),
  color: z
    .enum(["default", "primary", "success", "warning", "danger"])
    .optional(),
  label: z.string().optional(),
  showValue: z.boolean().optional(),
  width: z.enum(["sm", "md", "lg", "full"]).optional(),
});

export const avatarSchema = z.object({
  name: z.string(),
  initials: z.string().optional(),
  image: z.string().optional(),
  color: z
    .enum(["primary", "success", "warning", "danger", "default"])
    .optional(),
  showName: z.boolean().optional(),
});

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export const timelineSchema = z.object({
  items: z.array(
    z.object({
      time: z.string(),
      title: z.string(),
      description: z.string().optional(),
      status: z.enum(["success", "error", "warning", "neutral"]).optional(),
      actor: z.string().optional(),
      links: z
        .array(
          z.object({
            label: z.string(),
            url: z.string(),
            type: z.enum(["primary", "secondary"]).optional(),
          }),
        )
        .optional(),
      actions: z
        .array(
          z.object({
            label: z.string(),
            value: z.string(),
          }),
        )
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const textDocumentSchema = z.object({
  title: z.string(),
  body: z.string(),
  fields: z
    .array(z.object({ label: z.string(), value: z.string() }))
    .optional(),
});

// ---------------------------------------------------------------------------
// Spec registry — single source for the prompt generator
// ---------------------------------------------------------------------------

/**
 * The GAIA-only components `@openuidev/react-ui` has no equivalent for. Each
 * `description` here MUST stay identical to the matching `defineComponent`
 * call in the component file — the renderer and the LLM prompt read the same
 * vocabulary.
 */
export const GAIA_COMPONENT_SPECS = [
  {
    name: "GaugeChart",
    description: "Radial gauge for a value with min/max bounds.",
    props: gaugeChartSchema,
  },
  {
    name: "MapBlock",
    description: "OpenStreetMap embed for a lat/lng location.",
    props: mapBlockSchema,
  },
  {
    name: "NumberTicker",
    description: "Animated count-up number display.",
    props: numberTickerSchema,
  },
  {
    name: "VideoBlock",
    description: "YouTube/Vimeo embed or native video player.",
    props: videoBlockSchema,
  },
  {
    name: "AudioPlayer",
    description: "Audio player with title and description.",
    props: audioPlayerSchema,
  },
  {
    name: "ImageGallery",
    description: "Grid of images with captions.",
    props: imageGallerySchema,
  },
  {
    name: "CopyableContent",
    description:
      "Copyable non-code text content, supports inline chips and long form blocks.",
    props: copyableContentSchema,
  },
  {
    name: "FileTree",
    description:
      "File/directory tree (variant='file') or generic collapsible tree (variant='generic').",
    props: fileTreeSchema,
  },
  {
    name: "KbdRow",
    description:
      "A single keyboard shortcut row — keys + description. Compose inside a Card for a shortcut table.",
    props: kbdRowSchema,
  },
  {
    name: "Progress",
    description: "Progress bar with optional label and value display.",
    props: progressSchema,
  },
  {
    name: "Avatar",
    description: "User avatar with name label.",
    props: avatarSchema,
  },
  {
    name: "Timeline",
    description:
      "Chronological event feed with timestamps, status dots, optional actor, links, and actions.",
    props: timelineSchema,
  },
  {
    name: "TextDocument",
    description:
      "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
    props: textDocumentSchema,
  },
] as const;
