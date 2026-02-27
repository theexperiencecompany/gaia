import React from "react";
import { Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { Clock01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";

interface WorkflowDraftVideoCardProps {
  title: string;
  description?: string;
  schedule?: string;
  animProgress?: number;
  cardScale?: number;
}

/**
 * Video-native recreation of WorkflowDraftCard from the web app.
 * Translates Tailwind/HeroUI styles to inline styles for Remotion rendering.
 *
 * Design reference: apps/web/src/features/workflows/components/WorkflowDraftCard.tsx
 * - Container: rounded-3xl, border-dashed border-warning/40, bg-zinc-800/40, p-4
 * - "Draft" chip: absolute -top-2 -right-2, bg-warning/20, text-warning
 * - Icon box: bg-primary/15, text-primary
 * - Subtitle: "Review to create workflow", text-warning/80
 * - Trigger chip: bg-primary/15
 * - Button: "Review & Create"
 */
export const WorkflowDraftVideoCard: React.FC<WorkflowDraftVideoCardProps> = ({
  title,
  description,
  schedule = "Every day at 8:00 AM",
  animProgress = 1,
  cardScale = 1,
}) => {
  const warningColor = "#f59e0b";

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        gap: 22,
        width: 700,
        borderRadius: 24,
        border: `2px dashed ${warningColor}55`,
        background: "#1e1e21",
        padding: 36,
        transform: `scale(${cardScale})`,
        opacity: animProgress,
        transformOrigin: "top left",
      }}
    >
      {/* Draft chip — absolute top-right */}
      <div
        style={{
          position: "absolute",
          top: -12,
          right: -12,
          padding: "5px 14px",
          borderRadius: 20,
          background: `${warningColor}33`,
          color: warningColor,
          fontSize: 13,
          fontFamily: FONTS.body,
          fontWeight: 600,
        }}
      >
        Draft
      </div>

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* Icon box */}
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 18,
              background: `${COLORS.primary}26`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              overflow: "hidden",
            }}
          >
            <Img
              src={staticFile("images/logos/logo.webp")}
              style={{ width: 40, height: 40, objectFit: "contain" }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span
              style={{
                fontSize: 24,
                fontWeight: 500,
                color: "white",
                fontFamily: FONTS.body,
                lineHeight: 1.3,
              }}
            >
              {title}
            </span>
            <span style={{ fontSize: 16, color: `${warningColor}cc`, fontFamily: FONTS.body }}>
              Review to create workflow
            </span>
          </div>
        </div>

        {/* Schedule chip */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "6px 16px",
            borderRadius: 20,
            background: `${COLORS.primary}22`,
            color: COLORS.primary,
            fontSize: 15,
            fontFamily: FONTS.body,
            fontWeight: 500,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          <Clock01Icon size={16} color={COLORS.primary} style={{ marginRight: 6, flexShrink: 0 }} />
          {schedule}
        </div>
      </div>

      {/* Description */}
      {description && (
        <p
          style={{
            fontSize: 16,
            color: COLORS.zinc400,
            fontFamily: FONTS.body,
            lineHeight: 1.6,
            margin: 0,
          }}
        >
          {description}
        </p>
      )}

      {/* Review & Create button */}
      <div
        style={{
          width: "100%",
          padding: "16px 0",
          borderRadius: 16,
          background: `${COLORS.primary}22`,
          color: COLORS.primary,
          fontSize: 17,
          fontWeight: 500,
          fontFamily: FONTS.body,
          textAlign: "center",
        }}
      >
        Review &amp; Create
      </div>
    </div>
  );
};
