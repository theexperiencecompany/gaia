import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { updatesKeys } from "../api/queryKeys";
import { updatesApi } from "../api/updatesApi";
import { useUpdatesSeenStore } from "../stores/updatesSeenStore";

export function useUnseenUpdates(): number {
  const lastSeenAt = useUpdatesSeenStore((state) => state.lastSeenAt);
  const startCounting = useUpdatesSeenStore((state) => state.startCounting);

  useEffect(startCounting, [startCounting]);

  const { data } = useQuery({
    queryKey: updatesKeys.unseen(lastSeenAt ?? ""),
    queryFn: () => updatesApi.unseen(lastSeenAt ?? ""),
    enabled: lastSeenAt !== null,
  });

  return data?.count ?? 0;
}
