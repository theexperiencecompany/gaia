"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  CheckmarkCircle02Icon,
  CopyIcon,
  Mail01Icon,
  NewTwitterIcon,
  PencilEdit01Icon,
  SentIcon,
  WhatsappIcon,
} from "@icons";
import { type KeyboardEvent, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { useInviteFriends, useUpdateReferralCode } from "../hooks/useReferrals";

const SHARE_MESSAGE =
  "I've been using GAIA — a proactive personal AI assistant. Here's 50% off your first 2 months of PRO:";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface ShareZoneProps {
  shareLink: string;
  code: string;
}

export function ShareZone({ shareLink, code }: ShareZoneProps) {
  const [copied, setCopied] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailDraft, setEmailDraft] = useState("");
  const [editingCode, setEditingCode] = useState(false);
  const [codeDraft, setCodeDraft] = useState(code);

  const invite = useInviteFriends();
  const updateCode = useUpdateReferralCode();

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareLink);
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy — try selecting the link manually");
    }
  };

  const openWhatsApp = () => {
    const text = encodeURIComponent(`${SHARE_MESSAGE} ${shareLink}`);
    window.open(`https://wa.me/?text=${text}`, "_blank", "noopener");
  };

  const openX = () => {
    const text = encodeURIComponent(SHARE_MESSAGE);
    const url = encodeURIComponent(shareLink);
    window.open(
      `https://twitter.com/intent/tweet?text=${text}&url=${url}`,
      "_blank",
      "noopener",
    );
  };

  const sendInvites = () => {
    const emails = emailDraft
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter(Boolean);
    const valid = emails.filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter at least one valid email address");
      return;
    }
    invite.mutate(valid, {
      onSuccess: () => {
        setEmailDraft("");
        setEmailOpen(false);
      },
    });
  };

  const saveCode = () => {
    // Enter + blur can both call this; ignore re-entry while a save is in flight.
    if (updateCode.isPending) return;
    const next = codeDraft.trim();
    if (!next || next === code) {
      setEditingCode(false);
      setCodeDraft(code);
      return;
    }
    updateCode.mutate(next, {
      onSuccess: () => setEditingCode(false),
    });
  };

  const onEmailKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      sendInvites();
    }
  };

  return (
    <div className="space-y-4">
      {/* Share link field over a faint illustrative backdrop. */}
      <div className="relative overflow-hidden rounded-2xl bg-zinc-900/60 p-1.5">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -right-10 -top-16 size-48 rounded-full bg-primary/10 blur-3xl" />
          <div className="absolute -bottom-20 left-10 size-40 rounded-full bg-primary/[0.06] blur-3xl" />
        </div>
        <div className="relative flex items-center gap-2">
          {editingCode ? (
            <Input
              autoFocus
              value={codeDraft}
              onValueChange={setCodeDraft}
              onKeyDown={(e) => e.key === "Enter" && saveCode()}
              onBlur={saveCode}
              placeholder="your-vanity-code"
              variant="flat"
              classNames={{
                inputWrapper: "bg-zinc-800/60 data-[hover=true]:bg-zinc-800",
                input: "font-mono text-sm text-zinc-100",
              }}
            />
          ) : (
            <Input
              readOnly
              value={shareLink}
              variant="flat"
              classNames={{
                inputWrapper:
                  "bg-zinc-800/40 backdrop-blur-xl data-[hover=true]:bg-zinc-800/60",
                input: "font-mono text-sm text-zinc-200",
              }}
            />
          )}
          <RaisedButton
            type="button"
            onClick={handleCopy}
            className="h-12 shrink-0 gap-1.5 px-5 font-semibold text-black"
          >
            {copied ? (
              <CheckmarkCircle02Icon size={18} />
            ) : (
              <CopyIcon size={18} />
            )}
            {copied ? "Copied" : "Copy"}
          </RaisedButton>
        </div>
      </div>

      {/* Share channels. */}
      <div className="flex flex-wrap items-center gap-2">
        <ShareChip icon={<WhatsappIcon size={16} />} onPress={openWhatsApp}>
          WhatsApp
        </ShareChip>
        <ShareChip icon={<NewTwitterIcon size={16} />} onPress={openX}>
          Post on X
        </ShareChip>
        <ShareChip
          icon={<Mail01Icon size={16} />}
          onPress={() => setEmailOpen((v) => !v)}
          active={emailOpen}
        >
          Invite by email
        </ShareChip>
        <button
          type="button"
          onClick={() => {
            setEditingCode((v) => !v);
            setCodeDraft(code);
          }}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <PencilEdit01Icon size={14} />
          {editingCode ? "Done" : "Edit link"}
        </button>
      </div>

      {/* Email invite drawer. */}
      {emailOpen && (
        <div className="flex items-center gap-2">
          <Input
            autoFocus
            value={emailDraft}
            onValueChange={setEmailDraft}
            onKeyDown={onEmailKeyDown}
            placeholder="friend@email.com, another@email.com"
            type="text"
            variant="flat"
            classNames={{
              inputWrapper: "bg-zinc-900/60 data-[hover=true]:bg-zinc-900",
              input: "text-sm text-zinc-100",
            }}
          />
          <Button
            color="primary"
            className="h-12 shrink-0 px-5 font-semibold text-black"
            isLoading={invite.isPending}
            onPress={sendInvites}
            startContent={
              !invite.isPending ? <SentIcon size={16} /> : undefined
            }
          >
            Send
          </Button>
        </div>
      )}
    </div>
  );
}

function ShareChip({
  icon,
  onPress,
  active = false,
  children,
}: {
  icon: React.ReactNode;
  onPress: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onPress}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary/15 text-primary"
          : "bg-zinc-800/60 text-zinc-300 hover:bg-zinc-800",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
