import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import { MoreHorizontalIcon, ShieldIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalScope,
  ApprovalStatus,
} from "@shared/chat";
import { useState } from "react";
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
    <div className="mt-3 space-y-1.5 rounded-2xl bg-zinc-900 p-3">
      {rows.map(([key, value]) => (
        <div key={key} className="flex gap-2 text-xs">
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
      // The group moves it into the receipts list — it is not thrown away.
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
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="flex items-start gap-2">
        <ShieldIcon width={18} className="mt-0.5 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-zinc-100">{data.summary}</div>
          <div className="text-xs text-zinc-500">Approval required</div>
        </div>
      </div>

      <ArgsPreview args={data.args_preview} />

      <Input
        className="mt-3"
        size="sm"
        variant="flat"
        placeholder="Optional: tell GAIA why (or what to do instead)"
        value={feedback}
        onValueChange={setFeedback}
        isDisabled={locked}
      />
      <div className="mt-3 flex items-center gap-2">
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
    </div>
  );
}
