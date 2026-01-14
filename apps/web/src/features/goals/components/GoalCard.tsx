import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Tooltip } from "@heroui/tooltip";
import { useRouter } from "next/navigation";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { goalsApi } from "@/features/goals/api/goalsApi";
import { useConfirmation } from "@/hooks/useConfirmation";
import {
  Calendar03Icon,
  CheckmarkCircle02Icon,
  MoreVerticalIcon,
} from "@/icons";
import type { Goal } from "@/types/api/goalsApiTypes";
import { parseDate2 } from "@/utils";

export function GoalCard({
  goal,
  fetchGoals,
}: {
  goal: Goal;
  fetchGoals: () => void;
}) {
  const router = useRouter();
  const { confirm, confirmationProps } = useConfirmation();

  async function deleteGoal(goalId: string) {
    try {
      await goalsApi.deleteGoal(goalId);
      fetchGoals();
    } catch (error) {
      console.error("Error deleting goal:", error);
    }
  }

  const handleDelete = async () => {
    const confirmed = await confirm({
      title: "Delete Roadmap",
      message: `Are you sure you want to delete the roadmap titled "${goal?.roadmap?.title || goal.title}"? This action cannot be undone.`,
      confirmText: "Delete",
      cancelText: "Close",
      variant: "destructive",
    });

    if (!confirmed) return;
    await deleteGoal(goal?.id);
  };

  // Calculate steps info
  const nodes = goal.roadmap?.nodes || [];
  const totalSteps = nodes.length;
  const completedSteps = nodes.filter((node) => node.data?.isComplete).length;
  const hasSteps = totalSteps > 0;

  return (
    <>
      <div className="group bg-opacity-50 flex w-full flex-col rounded-2xl bg-surface-200 p-4">
        <div className="relative flex w-full items-center gap-2">
          <span className="w-[90%] truncate">
            {goal?.roadmap?.title || goal.title}
          </span>

          <div className="absolute -right-2 opacity-0 transition-opacity group-hover:opacity-100">
            <Dropdown
              classNames={{
                content: "bg-surface-100",
              }}
            >
              <DropdownTrigger>
                <Button isIconOnly variant="flat" size="sm">
                  <MoreVerticalIcon />
                </Button>
              </DropdownTrigger>
              <DropdownMenu aria-label="Static Actions">
                <DropdownItem
                  key="delete"
                  className="text-danger"
                  color="danger"
                  onPress={handleDelete}
                >
                  Delete Roadmap
                </DropdownItem>
              </DropdownMenu>
            </Dropdown>
          </div>
        </div>

        <div className="my-3 flex items-center justify-between gap-2">
          <div className="relative h-3 w-[100%] rounded-full">
            <div
              className={`absolute top-0 left-0 z-[2] h-3 rounded-full bg-primary`}
              style={{ width: `${goal?.progress || 0}%` }}
            />

            <div
              className={`absolute top-0 left-0 h-3 w-full rounded-full bg-surface-100`}
            />
          </div>
          <span className="text-xs">{goal?.progress || 0}%</span>
        </div>

        <div className="flex cursor-default items-center justify-start gap-2 flex-wrap">
          <Chip
            color={
              !goal.roadmap?.nodes?.length || !goal.roadmap?.edges?.length
                ? "warning"
                : (goal.progress || 0) === 100
                  ? "success"
                  : (goal.progress || 0) > 0
                    ? "primary"
                    : "warning"
            }
            size="sm"
            variant="flat"
          >
            {!goal.roadmap?.nodes?.length || !goal.roadmap?.edges?.length
              ? "Not Started"
              : (goal.progress || 0) === 100
                ? "Completed"
                : (goal.progress || 0) > 0
                  ? "In Progress"
                  : "Not Started"}
          </Chip>

          {/* Steps chip */}
          {hasSteps && (
            <Chip
              size="sm"
              variant="flat"
              className="text-foreground-400 px-1"
              radius="sm"
              startContent={
                <CheckmarkCircle02Icon
                  width={15}
                  height={15}
                  className="mx-1"
                />
              }
            >
              {completedSteps}/{totalSteps} steps
            </Chip>
          )}

          <Tooltip content="Created on" size="sm" showArrow placement="bottom">
            <div className="flex cursor-default items-center gap-1 text-xs text-foreground-500">
              <Calendar03Icon width={16} />
              {parseDate2(goal?.created_at || new Date().toISOString())}
            </div>
          </Tooltip>

          <Button
            color="primary"
            size="sm"
            className="ml-auto font-medium"
            onPress={() => router.push(`/goals/${goal.id}`)}
          >
            View Goal
          </Button>
        </div>
      </div>

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
