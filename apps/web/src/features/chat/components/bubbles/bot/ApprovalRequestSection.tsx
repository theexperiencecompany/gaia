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
import { formatApprovalAge, RECONFIRM_AGE_SECONDS } from "@shared/chat";
import { flattenArgsPreview, statusAfterDecision } from "@shared/utils";
import { useMemo, useRef, useState } from "react";
import { ShieldAlertIcon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { toast } from "@/lib/toast";

interface ApprovalRequestSectionProps {
  data: ApprovalRequestData;
  onDecided: (status: ApprovalStatus, feedback: string | null) => void;
  /** A batch decision ("Approve all"/"Decline all") is in flight — lock this card
   * so a per-card click can't send a second, conflicting decision for the same id. */
  disabled?: boolean;
  /** The conversation owning this card — clears that stream's gate instead of
   * the active one (a sheet or background card can outlive the active chat). */
  conversationId?: string;
}

// Statuses a stale tap settles to locally (the real verdict, not the tap);
// `pending`/`unknown` keep the retry toast, `executing` is a ledger transient.
function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const { rows, omitted } = useMemo(() => flattenArgsPreview(args), [args]);
  if (rows.length === 0) return null;
  let lastGroup: string | null = null;
  return (
    <div className="mt-3 space-y-2 rounded-2xl bg-zinc-900 p-3">
      {rows.map((row) => {
        const showGroup = row.group !== null && row.group !== lastGroup;
        lastGroup = row.group;
        return (
          <div key={`${row.group ?? "top"}:${row.key}:${row.value}`}>
            {showGroup && (
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                {row.group}
              </div>
            )}
            <div className="text-xs">
              <div className="mb-0.5 text-[11px] text-zinc-500">
                {row.key.replace(/^./, (char) => char.toUpperCase())}
              </div>
              <div className="text-zinc-200">{row.value}</div>
            </div>
          </div>
        );
      })}
      {omitted > 0 && (
        <div className="text-[11px] text-zinc-500">+{omitted} more</div>
      )}
    </div>
  );
}

type Phase = "idle" | "reconfirm" | "submitting";

export default function ApprovalRequestSection({
  data,
  onDecided,
  disabled = false,
  conversationId,
}: ApprovalRequestSectionProps) {
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [feedback, setFeedback] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  // A stale-v tap committed nothing; the next submit omits v so the CAS —
  // not the version check — decides. v is an optimization, never a gate. Read
  // and written only inside submit, never in render — a ref, not state.
  const versionConflict = useRef(false);
  const markApprovalDecided = useMarkApprovalDecided();
  const locked = submitting !== null || disabled || phase === "submitting";

  const needsReconfirm = (data.age_seconds ?? 0) >= RECONFIRM_AGE_SECONDS;

  const submit = async (
    decision: ApprovalDecision,
    scope: ApprovalScope = "once",
  ) => {
    setSubmitting(decision);
    setPhase("submitting");
    // Feedback rides deny only (sheet parity): an approve-with-note would
    // execute beyond the granted permission, so the server converts it to
    // deny — the card says so from the start.
    const attachedFeedback =
      decision === "deny" ? feedback.trim() || null : null;
    try {
      const outcome = await chatApi.postApprovalDecision(data.approval_id, {
        decision,
        feedback: attachedFeedback ?? undefined,
        scope,
        v: versionConflict.current
          ? undefined
          : (data.ledger_version ?? undefined),
      });
      // Settle locally: the resolved frame (websocket broadcast or reload) flips
      // the card to the real outcome — executed, failed, unknown. Reaching the
      // catch means the submit genuinely failed.
      const settled = statusAfterDecision(decision, outcome);
      if (settled === null) {
        // Stale version: drop it so the next tap hits the CAS directly.
        versionConflict.current = true;
        setSubmitting(null);
        setPhase("idle");
        toast.error("That approval already moved — tap again to confirm");
        return;
      }
      markApprovalDecided(conversationId);
      onDecided(settled, attachedFeedback);
    } catch {
      toast.error("Couldn't submit your decision, please try again");
      setSubmitting(null);
      setPhase("idle");
    }
  };

  const onApproveTap = () => {
    if (needsReconfirm && phase === "idle") {
      setPhase("reconfirm");
      return;
    }
    // No commit grace: the tap IS the decision. The ledger CAS makes a
    // double tap harmless, so there is nothing a waiting room would protect.
    void submit("approve");
  };

  if (data.status !== "pending") return null;

  if (phase === "reconfirm") {
    return (
      <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
        <div className="text-sm leading-snug text-zinc-100">
          {`Asked ${formatApprovalAge(data.age_seconds).replace("asked ", "")} ago — still want this?`}
        </div>
        <div className="mt-1 text-xs text-zinc-400">{data.summary}</div>
        <div className="mt-3 flex items-center gap-2">
          <Button
            color="primary"
            size="sm"
            onPress={() => {
              setPhase("idle");
              onApproveTap();
            }}
          >
            Yes, still approve
          </Button>
          <Button variant="flat" size="sm" onPress={() => setPhase("idle")}>
            Back
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="flex items-start gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-amber-400/10">
          <ShieldAlertIcon width={17} height={17} className="text-amber-400" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-amber-400">
            Needs approval
          </div>
          <div className="text-sm leading-snug text-zinc-100">
            {formatToolName(data.gated_tool_name)}
          </div>
          {data.age_seconds != null && (
            <div className="mt-0.5 text-[11px] text-zinc-500">
              {formatApprovalAge(data.age_seconds)}
            </div>
          )}
        </div>
      </div>

      {data.rationale?.trim() && (
        <div className="mt-2 text-xs leading-snug text-zinc-400">
          {data.rationale.trim()}
        </div>
      )}

      <ArgsPreview args={data.args_preview} />

      <div className="mt-3 flex items-center gap-2">
        <Input
          className="flex-1"
          size="sm"
          variant="flat"
          placeholder="Tell GAIA why (optional)"
          value={feedback}
          onValueChange={setFeedback}
          isDisabled={locked}
        />
        <Button
          color="primary"
          size="sm"
          isDisabled={locked}
          onPress={onApproveTap}
        >
          Approve
        </Button>
        <Button
          variant="flat"
          size="sm"
          isDisabled={locked}
          onPress={() => submit("deny")}
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
              onPress={() => submit("approve", "always_tool")}
            >
              Always allow this tool
            </DropdownItem>
          </DropdownMenu>
        </Dropdown>
      </div>
    </div>
  );
}
