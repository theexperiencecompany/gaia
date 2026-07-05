import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import { MoreHorizontalIcon, ShieldIcon } from "@icons";
import type { ApprovalRequestData } from "@shared/chat";
import { useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { toast } from "@/lib/toast";

interface ApprovalRequestSectionProps {
  data: ApprovalRequestData;
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
}: ApprovalRequestSectionProps) {
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [feedback, setFeedback] = useState("");

  const decide = async (
    decision: "approve" | "deny",
    scope: "once" | "always_tool" = "once",
  ) => {
    setSubmitting(decision);
    try {
      await chatApi.postApprovalDecision(data.approval_id, {
        decision,
        feedback: feedback.trim() || undefined,
        scope,
      });
      // The resolved frame arrives over the stream and replaces this card; a 410
      // (already resolved elsewhere) is swallowed by postApprovalDecision, so
      // reaching this catch means the decision genuinely failed to submit.
    } catch {
      toast.error("Couldn't submit your decision — please try again");
      setSubmitting(null);
    }
  };

  // A settled approval is removed entirely — nobody acts on a decided card, and
  // the assistant's own reply already reflects the outcome. Only pending cards
  // render (the group also filters, this keeps the component self-consistent).
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
        isDisabled={submitting !== null}
      />
      <div className="mt-3 flex items-center gap-2">
        <Button
          color="primary"
          size="sm"
          isLoading={submitting === "approve"}
          isDisabled={submitting !== null}
          onPress={() => decide("approve")}
        >
          Approve
        </Button>
        <Button
          variant="flat"
          size="sm"
          isLoading={submitting === "deny"}
          isDisabled={submitting !== null}
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
              isDisabled={submitting !== null}
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
