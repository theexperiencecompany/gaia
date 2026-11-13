/**
 * Payloads for the chat cards TOOL_RENDERERS draws that libs/shared/ts/src/chat/fixtures.ts
 * has no fixture for. Shapes follow apps/web/src/config/registries/toolRegistry.ts.
 */

import { PNG } from "pngjs";

/** A 160x100 solid zinc-800 thumbnail, the data-URL shape the desktop screenshot tool emits. */
function thumbnail() {
  const png = new PNG({ width: 160, height: 100 });
  for (let i = 0; i < png.data.length; i += 4) png.data.set([39, 39, 42, 255], i);
  return `data:image/png;base64,${PNG.sync.write(png).toString("base64")}`;
}
const THUMBNAIL = thumbnail();

export const EXTRA_TOOL_FIXTURES = [
  {
    toolName: "calendar_options",
    label: "Calendar event proposal",
    data: [
      {
        summary: "Design review with Priya",
        description: "Walk through the v3 component parity report.",
        start: "2026-11-14T10:00:00+05:30",
        end: "2026-11-14T10:45:00+05:30",
        calendar_id: "primary",
        calendar_name: "Work",
        background_color: "#00bbff",
        attendees: ["priya@example.com"],
        create_meeting_room: true,
      },
    ],
  },
  {
    toolName: "connect_options",
    label: "Connect options",
    data: {
      options: [
        { integration_id: "gmail", label: "Connect Gmail", href: "/integrations?id=gmail" },
        { integration_id: "googlecalendar", label: "Connect Google Calendar", href: "/integrations?id=googlecalendar" },
      ],
    },
  },
  {
    toolName: "device_onboarding_required",
    label: "Device onboarding",
    data: {
      install_commands: { npm: "npm i -g @heygaia/cli", pnpm: "pnpm add -g @heygaia/cli", bun: "bun add -g @heygaia/cli" },
      docs_url: "https://docs.heygaia.io/cli",
      pair_command: "gaia connect",
      up_command: "gaia up",
      message: "Install the GAIA CLI on the machine you want me to use.",
    },
  },
  {
    toolName: "device_approval_required",
    label: "Device approval",
    data: {
      approve_url: "/settings/devices/approve?code=KQ7M-2XPD",
      code: "KQ7M-2XPD",
      message: "A machine is waiting for you to approve it.",
    },
  },
  {
    toolName: "approval_request",
    label: "Approval request",
    data: {
      approval_id: "appr_review_0001",
      tool_call_id: "call_review_0001",
      gated_tool_name: "GMAIL_SEND_EMAIL",
      integration_name: "Gmail",
      summary: "Send the weekly status email to the team",
      args_preview: { to: "team@example.com", subject: "Weekly status" },
      status: "pending",
      feedback: null,
      timeout_seconds: 3600,
      rationale: "You asked me to send it every Friday.",
      age_seconds: 120,
      ledger_version: 1,
      always_asks: false,
    },
  },
  {
    toolName: "screenshot_data",
    label: "Desktop screenshot",
    data: { thumbnail: THUMBNAIL, width: 1440, height: 900 },
  },
  {
    toolName: "browser_task_data",
    label: "Browser task result",
    data: {
      kind: "result",
      status: "completed",
      success: true,
      summary: "Booked a table for two at 8pm on Friday.",
      steps: 7,
      replay_url: null,
      user_notes: ["Confirmation was sent to your email."],
    },
  },
];
