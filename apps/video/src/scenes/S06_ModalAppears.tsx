import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";

// Placeholder modal UI — styled to match DemoWorkflowModal appearance
// In production, replace with actual DemoWorkflowModal import
const WorkflowModalMock: React.FC<{ phase: string }> = ({ phase: _phase }) => (
  <div
    style={{
      width: 900,
      height: 620,
      background: "#18181b",
      border: "1px solid #27272a",
      borderRadius: 16,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}
  >
    {/* Header */}
    <div
      style={{
        padding: "20px 24px",
        borderBottom: "1px solid #27272a",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <span
        style={{
          color: "white",
          fontSize: 18,
          fontWeight: 600,
          fontFamily: "Inter, sans-serif",
        }}
      >
        Create Workflow
      </span>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "#3f3f46",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#a1a1aa",
          fontSize: 14,
        }}
      >
        ✕
      </div>
    </div>

    {/* Body */}
    <div style={{ flex: 1, display: "flex" }}>
      {/* Left panel */}
      <div
        style={{
          flex: 1,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 20,
          borderRight: "1px solid #27272a",
        }}
      >
        {/* Title field */}
        <div>
          <div
            style={{
              fontSize: 13,
              color: "#a1a1aa",
              marginBottom: 8,
              fontFamily: "Inter, sans-serif",
            }}
          >
            Workflow Name
          </div>
          <div
            style={{
              background: "#27272a",
              border: "1px solid #3f3f46",
              borderRadius: 8,
              padding: "10px 14px",
              color: "#71717a",
              fontSize: 15,
              fontFamily: "Inter, sans-serif",
            }}
          >
            Name your workflow...
          </div>
        </div>

        {/* Description field */}
        <div>
          <div
            style={{
              fontSize: 13,
              color: "#a1a1aa",
              marginBottom: 8,
              fontFamily: "Inter, sans-serif",
            }}
          >
            Description
          </div>
          <div
            style={{
              background: "#27272a",
              border: "1px solid #3f3f46",
              borderRadius: 8,
              padding: "10px 14px",
              color: "#71717a",
              fontSize: 15,
              height: 100,
              fontFamily: "Inter, sans-serif",
            }}
          >
            Describe what this workflow does...
          </div>
        </div>

        {/* Trigger section */}
        <div>
          <div
            style={{
              fontSize: 13,
              color: "#a1a1aa",
              marginBottom: 8,
              fontFamily: "Inter, sans-serif",
            }}
          >
            Trigger
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {["Manual", "Schedule", "Event"].map((tab, i) => (
              <div
                key={i}
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  background: i === 0 ? "#3f3f46" : "transparent",
                  border: "1px solid #3f3f46",
                  color: i === 0 ? "white" : "#71717a",
                  fontSize: 13,
                  fontFamily: "Inter, sans-serif",
                }}
              >
                {tab}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div
        style={{
          width: 320,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            fontSize: 13,
            color: "#a1a1aa",
            marginBottom: 4,
            fontFamily: "Inter, sans-serif",
          }}
        >
          Steps
        </div>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              height: 56,
              background: "#27272a",
              borderRadius: 8,
              border: "1px solid #3f3f46",
              padding: "0 14px",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "#3f3f46",
              }}
            />
            <div
              style={{
                flex: 1,
                height: 10,
                background: "#3f3f46",
                borderRadius: 5,
              }}
            />
          </div>
        ))}
      </div>
    </div>

    {/* Footer */}
    <div
      style={{
        padding: "16px 24px",
        borderTop: "1px solid #27272a",
        display: "flex",
        justifyContent: "flex-end",
        gap: 12,
      }}
    >
      <div
        style={{
          padding: "10px 20px",
          borderRadius: 8,
          border: "1px solid #3f3f46",
          color: "#a1a1aa",
          fontSize: 14,
          fontFamily: "Inter, sans-serif",
        }}
      >
        Cancel
      </div>
      <div
        style={{
          padding: "10px 24px",
          borderRadius: 8,
          background: COLORS.primary,
          color: "#000",
          fontSize: 14,
          fontWeight: 700,
          fontFamily: "Inter, sans-serif",
        }}
      >
        Create Workflow
      </div>
    </div>
  </div>
);

export const S06_ModalAppears: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({ frame, fps, config: { damping: 20, stiffness: 100 } });
  const scale = interpolate(progress, [0, 1], [0.85, 1.0]);
  const y = interpolate(progress, [0, 1], [40, 0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <SceneBackground variant="mesh" meshOpacity={0.15} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            transform: `scale(${1.4 * scale}) translateY(${y}px)`,
            transformOrigin: "center center",
            opacity,
          }}
        >
          <WorkflowModalMock phase="modal_appear" />
        </div>
      </div>
    </AbsoluteFill>
  );
};
