import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { firstStepsApi } from "@/features/first-steps/api/firstStepsApi";
import {
  FIRST_STEPS_POLL_INTERVAL_MS,
  FIRST_STEPS_QUERY_KEY,
} from "@/features/first-steps/constants";
import { toast } from "@/lib/toast";
import type {
  FirstStepStatus,
  FirstStepsResponse,
} from "@/types/features/firstStepsTypes";

interface UseFirstSteps {
  steps: FirstStepStatus[];
  doneCount: number;
  totalCount: number;
  /** False until loaded, and once every step is done. A collapsed checklist is
   * still visible — it is the header alone. */
  isVisible: boolean;
  collapsed: boolean;
  toggleCollapsed: () => void;
}

/** Whether the checklist still has something to ask of the user. */
const hasOpenStep = (data: FirstStepsResponse): boolean =>
  data.steps.some((step) => !step.done);

/**
 * The activation checklist, shared by the card and the widget through one
 * react-query cache so both surfaces show the same progress and collapse
 * together.
 *
 * Freshness comes from three places (route change, surface mount, and a slow
 * poll while a step is open) since window-focus refetching is off globally.
 */
export function useFirstSteps(): UseFirstSteps {
  const qc = useQueryClient();
  const pathname = usePathname();

  const { data } = useQuery({
    queryKey: FIRST_STEPS_QUERY_KEY,
    queryFn: firstStepsApi.fetch,
    refetchOnMount: "always",
    refetchInterval: ({ state }) =>
      state.data && hasOpenStep(state.data)
        ? FIRST_STEPS_POLL_INTERVAL_MS
        : false,
  });

  useEffect(() => {
    qc.invalidateQueries({ queryKey: FIRST_STEPS_QUERY_KEY });
  }, [pathname, qc]);

  // Two quick clicks are two requests whose replies can land in either order.
  // Each mutation takes a ticket; only the newest may write the server's
  // reply or roll back, so a stale reply/rollback can't undo the newest click.
  const latestCollapse = useRef(0);
  const collapseMutation = useMutation({
    mutationFn: firstStepsApi.setCollapsed,
    // The chevron has to move on the click, not on the round trip: the request
    // only persists a preference the user has already expressed. The in-flight
    // GET is cancelled first, or it can land afterwards and undo the write.
    onMutate: async (collapsed) => {
      latestCollapse.current += 1;
      const ticket = latestCollapse.current;
      await qc.cancelQueries({ queryKey: FIRST_STEPS_QUERY_KEY });
      const previous = qc.getQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
      );
      qc.setQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
        (current) => current && { ...current, collapsed },
      );
      return { previous, ticket };
    },
    // The response is the whole checklist, so there is nothing to refetch.
    onSuccess: (checklist, _collapsed, context) => {
      if (context.ticket !== latestCollapse.current) return;
      qc.setQueryData(FIRST_STEPS_QUERY_KEY, checklist);
    },
    onError: (_error, _collapsed, context) => {
      if (context?.ticket === latestCollapse.current && context.previous) {
        qc.setQueryData<FirstStepsResponse>(
          FIRST_STEPS_QUERY_KEY,
          context.previous,
        );
      }
      toast.error("Couldn't save that.");
    },
  });

  const steps = data?.steps ?? [];
  const collapsed = data?.collapsed ?? false;

  return {
    steps,
    doneCount: steps.filter((step) => step.done).length,
    totalCount: steps.length,
    isVisible: data !== undefined && hasOpenStep(data),
    collapsed,
    toggleCollapsed: () => collapseMutation.mutate(!collapsed),
  };
}
