"use client";

import { Skeleton } from "@heroui/skeleton";
import { Switch } from "@heroui/switch";
import { InviteLinksSection } from "@/features/settings/components/members/InviteLinksSection";
import { MemberListSection } from "@/features/settings/components/members/MemberListSection";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useMembers } from "@/features/settings/hooks/useMembers";

/** Admin-only: who can use this self-hosted GAIA and how new people join. */
export function MembersSettings() {
  const members = useMembers();
  const { overview } = members;

  return (
    <SettingsPage>
      <div>
        <h2 className="text-lg font-medium text-white">Members</h2>
        <p className="mt-1 text-sm leading-relaxed text-zinc-400">
          Everyone here gets their own chats, tasks and connected apps. AI
          provider keys are shared, and only you can change them.
        </p>
      </div>

      {members.isLoading && <Skeleton className="h-40 rounded-2xl" />}
      {members.error && (
        <p className="text-sm text-red-400">Could not load members.</p>
      )}
      {overview && (
        <>
          <SettingsSection title="Sign-up">
            <SettingsRow
              label="Open sign-up"
              description="Anyone who can reach this GAIA can create an account. When off, people need an invite link."
            >
              <Switch
                size="sm"
                aria-label="Open sign-up"
                isSelected={overview.registration_policy === "open"}
                isDisabled={members.isSettingPolicy}
                onValueChange={(open) =>
                  members.setPolicy(open ? "open" : "invite_only")
                }
              />
            </SettingsRow>
          </SettingsSection>

          <InviteLinksSection
            invites={overview.invites}
            onCreate={(onCreated) =>
              members.createInvite(undefined, {
                onSuccess: (created) => onCreated(created.token),
              })
            }
            isCreating={members.isCreatingInvite}
            onRevoke={members.revokeInvite}
            revokingInviteId={members.revokingInviteId}
          />

          <MemberListSection
            members={overview.members}
            onRemove={members.removeMember}
            removingUserId={members.removingUserId}
          />
        </>
      )}
    </SettingsPage>
  );
}
