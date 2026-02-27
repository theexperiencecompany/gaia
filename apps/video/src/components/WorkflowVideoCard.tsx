import React from "react";
import { Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { Clock01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";

interface WorkflowVideoCardProps {
  title: string;
  description?: string;
  schedule?: string;
  status?: "ready" | "running" | "done";
  animProgress?: number;
  cardScale?: number;
}

/**
 * Video-native recreation of WorkflowCreatedCard from the web app.
 * Translates Tailwind/HeroUI styles to inline styles for Remotion rendering.
 *
 * Design reference: apps/web/src/features/workflows/components/WorkflowCreatedCard.tsx
 * - Container: max-w-md, rounded-3xl, bg-zinc-800/40, p-4, outline-1 outline-zinc-800/50
 * - Icon box: size-10, rounded-xl, bg-success/15 (done) or bg-primary/15 (running/ready)
 * - Title: text-base font-medium
 * - Subtitle: text-xs text-zinc-500
 * - Created chip: bg-success/15, text-success
 * - Trigger: bg-primary/15, text-primary, clock icon
 * - Button: rounded-xl font-medium w-full
 */
export const WorkflowVideoCard: React.FC<WorkflowVideoCardProps> = ({
  title,
  description,
  schedule = "Every day at 8:00 AM",
  status = "ready",
  animProgress = 1,
  cardScale = 1,
}) => {
  const isDone = status === "done";
  const isRunning = status === "running";

  const iconBg = isDone ? "rgba(34,197,94,0.15)" : `${COLORS.primary}26`;
  const statusColor = isDone ? "#22c55e" : isRunning ? COLORS.primary : COLORS.zinc400;
  const statusBg = isDone ? "rgba(34,197,94,0.15)" : isRunning ? `${COLORS.primary}26` : "rgba(63,63,70,0.4)";
  const statusLabel = isDone ? "✓  Created" : isRunning ? "Running..." : "Ready";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 22,
        width: 700,
        borderRadius: 24,
        background: "#1e1e21",
        padding: 36,
        transform: `scale(${cardScale})`,
        opacity: animProgress,
        transformOrigin: "top left",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* Icon box */}
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 18,
              background: iconBg,
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
            <span style={{ fontSize: 16, color: COLORS.zinc500, fontFamily: FONTS.body }}>
              {isDone ? "Workflow Created" : "Workflow"}
            </span>
          </div>
        </div>

        {/* Status chip */}
        <div
          style={{
            padding: "6px 16px",
            borderRadius: 20,
            background: statusBg,
            color: statusColor,
            fontSize: 16,
            fontFamily: FONTS.body,
            fontWeight: 600,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {statusLabel}
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

      {/* Trigger chip */}
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 16px",
          borderRadius: 20,
          background: `${COLORS.primary}22`,
          width: "fit-content",
        }}
      >
        <Clock01Icon size={18} style={{ color: COLORS.primary }} />
        <span
          style={{
            fontSize: 17,
            color: COLORS.primary,
            fontFamily: FONTS.body,
            fontWeight: 500,
          }}
        >
          {schedule}
        </span>
      </div>

      {/* Action button */}
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
        {isDone ? "View & Edit" : "Running..."}
      </div>
    </div>
  );
};
