import type { CronValidationResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { workflowKeys } from "../api/queryKeys";
import { workflowApi } from "../api/workflowApi";

/** Typing pause before the expression is sent to the server for its verdict. */
const CRON_VALIDATION_DEBOUNCE_MS = 400;

/** A verdict never changes for the same expression, so it is cached for the session. */
const CRON_VERDICT_STALE_TIME = Number.POSITIVE_INFINITY;

/** The server's verdict on expression, once typing pauses; undefined while empty or pending. */
export const useCronValidation = (
  expression: string,
): CronValidationResponse | undefined => {
  const trimmed = expression.trim();
  const [settled, setSettled] = useState(trimmed);

  useEffect(() => {
    const timer = setTimeout(
      () => setSettled(trimmed),
      CRON_VALIDATION_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [trimmed]);

  const { data } = useQuery({
    queryKey: workflowKeys.cronValidation(settled),
    queryFn: () => workflowApi.validateCron(settled),
    staleTime: CRON_VERDICT_STALE_TIME,
    enabled: settled.length > 0,
  });

  return settled === trimmed ? data : undefined;
};
