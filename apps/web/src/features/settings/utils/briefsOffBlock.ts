import { ApiError } from "@shared/api";
import type {
  BriefDeliveryWorkflow,
  BriefDeliveryWorkflowsConflict,
} from "@shared/api/generated";
import { z } from "zod";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";

const BriefDeliveryWorkflowsSchema = z.array(
  z.object({
    id: z.string(),
    title: z.string(),
  }) satisfies z.ZodType<BriefDeliveryWorkflow>,
);

/** A refused "off": the API's own words and the workflows still delivering to the brief. */
export type BriefsOffBlock = Pick<
  BriefDeliveryWorkflowsConflict,
  "message" | "workflows"
>;

/** What blocked turning briefs off, when that is why the save failed, else null. */
export function readBriefsOffBlock(error: unknown): BriefsOffBlock | null {
  if (
    !(error instanceof ApiError) ||
    error.code !== API_ERROR_CODES.BRIEF_DELIVERY_WORKFLOWS_EXIST
  ) {
    return null;
  }
  return {
    message: error.message,
    workflows: BriefDeliveryWorkflowsSchema.parse(error.envelope?.workflows),
  };
}
