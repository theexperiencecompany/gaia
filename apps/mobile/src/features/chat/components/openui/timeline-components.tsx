/**
 * Timeline & Notification components — re-exported from the OpenUI config layer.
 *
 * The implementations live in:
 *   apps/mobile/src/config/openui/components/timeline.tsx
 *
 * Components:
 * - Timeline: vertical event list with a 2 px gutter line, coloured halo dots,
 *   and status chips (success / error / warning / neutral).
 * - AlertBanner: icon + title + description panel tinted by variant
 *   (info / success / warning / error).
 * - Steps: ordered step list with complete (checkmark), active (cyan badge),
 *   and pending (numbered) states connected by a coloured gutter line.
 */
export {
  AlertBannerView,
  alertBannerDef,
  alertBannerSchema,
  StepsView,
  stepsDef,
  stepsSchema,
  TimelineView,
  timelineDef,
  timelineSchema,
} from "@/config/openui/components/timeline";
