"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Copy01Icon, UserAdd01Icon } from "@icons";
import type { InviteResponse } from "@shared/api/generated";
import { useRef, useState } from "react";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { inviteLink } from "@/features/settings/hooks/useMembers";
import { copyFieldText } from "@/lib/clipboard";
import { toast } from "@/lib/toast";
import { formatRelativeDate } from "@/utils/date/dateUtils";

interface InviteLinksSectionProps {
  invites: InviteResponse[];
  onCreate: (onCreated: (token: string) => void) => void;
  isCreating: boolean;
  onRevoke: (inviteId: string) => void;
  revokingInviteId: string | null | undefined;
}

async function copyLink(field: HTMLInputElement | null) {
  if (!field) {
    toast.error("Could not copy. Select the link and copy it yourself.");
    return;
  }
  if ((await copyFieldText(field)) === "copied") {
    toast.success("Invite link copied");
  } else {
    toast.info("Link selected. Press Ctrl+C (Cmd+C on a Mac) to copy it.");
  }
}

export function InviteLinksSection({
  invites,
  onCreate,
  isCreating,
  onRevoke,
  revokingInviteId,
}: InviteLinksSectionProps) {
  const [newLink, setNewLink] = useState<string | null>(null);
  const linkField = useRef<HTMLInputElement>(null);

  const create = () => onCreate((token) => setNewLink(inviteLink(token)));

  return (
    <SettingsSection
      title="Invite links"
      description="Each link lets one person create an account. Links expire after 7 days."
    >
      <SettingsRow
        label="New invite link"
        description="You can only copy a link right after you create it."
      >
        <Button
          size="sm"
          color="primary"
          startContent={<UserAdd01Icon width={16} height={16} />}
          isLoading={isCreating}
          onPress={create}
        >
          Create link
        </Button>
      </SettingsRow>
      {newLink && (
        <div className="px-4 py-3.5">
          <Input
            ref={linkField}
            aria-label="New invite link"
            value={newLink}
            isReadOnly
            size="sm"
            endContent={
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label="Copy invite link"
                onPress={() => void copyLink(linkField.current)}
              >
                <Copy01Icon width={16} height={16} />
              </Button>
            }
          />
        </div>
      )}
      {invites.map((invite) => (
        <SettingsRow
          key={invite.id}
          label="Unused invite link"
          description={`Expires ${formatRelativeDate(invite.expires_at)}`}
        >
          <Button
            size="sm"
            variant="flat"
            color="danger"
            isLoading={revokingInviteId === invite.id}
            onPress={() => onRevoke(invite.id)}
          >
            Revoke
          </Button>
        </SettingsRow>
      ))}
    </SettingsSection>
  );
}
