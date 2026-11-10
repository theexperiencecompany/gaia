"use client";

import type { RegistrationPolicy } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { membersApi } from "@/features/settings/api/membersApi";

const MEMBERS_QUERY_KEY = ["members"] as const;

/** The invite link a token opens: this instance's signup page. */
export function inviteLink(token: string): string {
  return `${window.location.origin}/signup?invite=${encodeURIComponent(token)}`;
}

/** The admin's view of the instance's accounts, invites and sign-up policy. */
export function useMembers() {
  const queryClient = useQueryClient();
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: MEMBERS_QUERY_KEY });

  const overview = useQuery({
    queryKey: MEMBERS_QUERY_KEY,
    queryFn: () => membersApi.getOverview(),
  });

  const createInvite = useMutation({
    mutationFn: () => membersApi.createInvite(),
    onSuccess: refresh,
  });
  const revokeInvite = useMutation({
    mutationFn: (inviteId: string) => membersApi.revokeInvite(inviteId),
    onSuccess: refresh,
  });
  const setPolicy = useMutation({
    mutationFn: (policy: RegistrationPolicy) =>
      membersApi.setRegistrationPolicy(policy),
    onSuccess: refresh,
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => membersApi.removeMember(userId),
    onSuccess: refresh,
  });

  return {
    overview: overview.data,
    isLoading: overview.isLoading,
    error: overview.error,
    createInvite: createInvite.mutate,
    isCreatingInvite: createInvite.isPending,
    revokeInvite: revokeInvite.mutate,
    revokingInviteId: revokeInvite.isPending ? revokeInvite.variables : null,
    setPolicy: setPolicy.mutate,
    isSettingPolicy: setPolicy.isPending,
    removeMember: removeMember.mutate,
    removingUserId: removeMember.isPending ? removeMember.variables : null,
  };
}
