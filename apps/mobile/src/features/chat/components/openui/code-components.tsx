/**
 * Code components — re-exported from the OpenUI config layer.
 *
 * The implementations live in:
 *   apps/mobile/src/config/openui/components/code.tsx
 *
 * Mobile-specific behaviour:
 * - CodeDiff renders two stacked CodeBlock panels (Before / After) with a
 *   red/green tint on each panel instead of the web @pierre/diffs unified diff.
 * - Syntax highlighting is handled by the shared mobile tokenizer used across
 *   the CodeBlock component.
 * - diffStyle, lineDiffType, diffIndicators, and expandUnchanged props are
 *   accepted for schema compatibility but have no visual effect on mobile.
 */
export {
  CodeDiffView,
  codeDiffDef,
  codeDiffSchema,
} from "@/config/openui/components/code";
