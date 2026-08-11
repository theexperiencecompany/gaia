import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import { MoreHorizontalIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalScope,
  ApprovalStatus,
} from "@shared/chat";
import { useState } from "react";
import { ShieldAlertIcon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { toast } from "@/lib/toast";

interface ApprovalRequestSectionProps {
  data: ApprovalRequestData;
  onDecided: (status: ApprovalStatus, feedback: string | null) => void;
  /** A batch decision ("Approve all"/"Decline all") is in flight — lock this card
   * so a per-card click can't send a second, conflicting decision for the same id. */
  disabled?: boolean;
}

function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const rows = Object.entries(args).filter(
    ([, value]) =>
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean",
  );
  if (rows.length === 0) return null;
  return (
    <div className="mt-2.5 space-y-1 rounded-2xl bg-zinc-900 p-3">
      {rows.map(([key, value]) => (
        <div key={key} className="flex gap-3 text-xs">
          <span className="shrink-0 text-zinc-500">{key}</span>
          <span className="min-w-0 flex-1 truncate text-right text-zinc-300">
            {String(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ApprovalRequestSection({
  data,
  onDecided,
  disabled = false,
}: ApprovalRequestSectionProps) {
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [feedback, setFeedback] = useState("");
  const locked = submitting !== null || disabled;

  const decide = async (
    decision: ApprovalDecision,
    scope: ApprovalScope = "once",
  ) => {
    setSubmitting(decision);
    try {
      await chatApi.postApprovalDecision(data.approval_id, {
        decision,
        feedback: feedback.trim() || undefined,
        scope,
      });
      // Settle locally: the resolved frame is published on the RESUMED run's
      // stream (a different message), so it never replaces this card. A 410
      // (already resolved elsewhere) is swallowed by postApprovalDecision and
      // settles here too; reaching the catch means the submit genuinely failed.
      onDecided(
        decision === "approve" ? "approved" : "denied",
        feedback.trim() || null,
      );
    } catch {
      toast.error("Couldn't submit your decision — please try again");
      setSubmitting(null);
    }
  };

  if (data.status !== "pending") return null;

  return (
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-3 text-white">
      <div className="flex items-center gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-amber-400/10">
          <ShieldAlertIcon width={17} height={17} className="text-amber-400" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-amber-400">
            Needs approval
          </div>
          <div className="truncate text-sm text-zinc-100">{data.summary}</div>
        </div>
        <Button
          color="primary"
          size="sm"
          isLoading={submitting === "approve"}
          isDisabled={locked}
          onPress={() => decide("approve")}
        >
          Approve
        </Button>
        <Button
          variant="flat"
          size="sm"
          isLoading={submitting === "deny"}
          isDisabled={locked}
          onPress={() => decide("deny")}
        >
          Deny
        </Button>
        <Dropdown placement="bottom-end">
          <DropdownTrigger>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              isDisabled={locked}
              aria-label="More approval options"
            >
              <MoreHorizontalIcon width={18} />
            </Button>
          </DropdownTrigger>
          <DropdownMenu aria-label="Approval options">
            <DropdownItem
              key="always"
              onPress={() => decide("approve", "always_tool")}
            >
              Always allow this tool
            </DropdownItem>
          </DropdownMenu>
        </Dropdown>
      </div>

      <ArgsPreview args={data.args_preview} />

      <Input
        className="mt-2.5"
        size="sm"
        variant="flat"
        placeholder="Optional: tell GAIA why (or what to do instead)"
        value={feedback}
        onValueChange={setFeedback}
        isDisabled={locked}
      />
    </div>
  );
}
