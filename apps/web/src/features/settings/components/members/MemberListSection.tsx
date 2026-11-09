"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type { MemberResponse } from "@shared/api/generated";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useConfirmation } from "@/hooks/useConfirmation";
import { formatRelativeDate } from "@/utils/date/dateUtils";

interface MemberListSectionProps {
  members: MemberResponse[];
  onRemove: (userId: string) => void;
  removingUserId: string | null | undefined;
}

function memberDescription(member: MemberResponse): string {
  const joined = member.created_at
    ? ` · Joined ${formatRelativeDate(member.created_at)}`
    : "";
  return `${member.email ?? ""}${joined}`;
}

export function MemberListSection({
  members,
  onRemove,
  removingUserId,
}: MemberListSectionProps) {
  const { confirm, confirmationProps } = useConfirmation();

  const remove = async (member: MemberResponse) => {
    const name = member.name ?? member.email ?? "This member";
    const confirmed = await confirm({
      title: "Remove member?",
      message: `${name} will be signed out and can't sign in again. Their workflows and reminders stop and their chat apps are unlinked; their chats and data stay on this instance.`,
      confirmText: "Remove",
      variant: "destructive",
    });
    if (confirmed) onRemove(member.user_id);
  };

  return (
    <SettingsSection title="People">
      {members.map((member) => (
        <SettingsRow
          key={member.user_id}
          label={member.name ?? member.email ?? member.user_id}
          description={memberDescription(member)}
        >
          {member.role === "admin" ? (
            <Chip size="sm" variant="flat">
              Admin
            </Chip>
          ) : (
            <Button
              size="sm"
              variant="flat"
              color="danger"
              isLoading={removingUserId === member.user_id}
              onPress={() => void remove(member)}
            >
              Remove
            </Button>
          )}
        </SettingsRow>
      ))}
      <ConfirmationDialog {...confirmationProps} />
    </SettingsSection>
  );
}
