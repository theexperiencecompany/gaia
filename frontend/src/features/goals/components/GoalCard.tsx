import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Tooltip } from "@heroui/tooltip";
import { DotsVerticalIcon } from "@radix-ui/react-icons";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  Calendar03Icon,
} from "@/components/shared/icons";
import { goalsApi } from "@/features/goals/api/goalsApi";
import { Goal } from "@/types/api/goalsApiTypes";
import { parseDate2 } from "@/utils";

export function GoalCard({
  goal,
  fetchGoals,
}: {
  goal: Goal;
  fetchGoals: () => void;
}) {
  const router = useRouter();
  const [openDeleteDialog, setOpenDeleteDialog] = useState(false);

  async function deleteGoal(goalId: string) {
    try {
      await goalsApi.deleteGoal(goalId);
      fetchGoals();
    } catch (error) {
      console.error("Error deleting goal:", error);
    }
  }

  const handleDelete = () => {
    deleteGoal(goal?.id);
    setOpenDeleteDialog(false);
  };

  console.log(goal);

  return (
    <>
      <Modal
        className="text-foreground dark"
        isOpen={openDeleteDialog}
        onOpenChange={setOpenDeleteDialog}
      >
        <ModalContent>
          <ModalHeader className="inline-block">
            Are you sure you want to delete the roadmap titled
            <span className="ml-1 font-normal text-primary-500">
              {goal?.roadmap?.title || goal.title}
            </span>
            <span className="ml-1">?</span>
          </ModalHeader>

          <ModalBody>
            <p className="font-medium text-danger-400">
              This action cannot be undone.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button
              color="danger"
              variant="light"
              onPress={() => setOpenDeleteDialog(false)}
            >
              Close
            </Button>
            <Button color="primary" onPress={handleDelete}>
              Delete
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <div className="group bg-opacity-50 flex w-full flex-col rounded-2xl bg-zinc-800 p-4">
        <div className="relative flex w-full items-center gap-2">
          <span className="w-[90%] truncate">
            {goal?.roadmap?.title || goal.title}
          </span>

          <div className="absolute -right-2 dark opacity-0 transition-opacity group-hover:opacity-100">
            <Dropdown
              classNames={{
                content: "bg-zinc-900",
              }}
            >
              <DropdownTrigger>
                <Button isIconOnly variant="flat" size="sm">
                  <DotsVerticalIcon />
                </Button>
              </DropdownTrigger>
              <DropdownMenu aria-label="Static Actions" className="dark">
                <DropdownItem
                  key="delete"
                  className="text-danger"
                  color="danger"
                  onPress={() => setOpenDeleteDialog(true)}
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
              className={`absolute top-0 left-0 h-3 w-full rounded-full bg-zinc-900`}
            />
          </div>
          <span className="text-xs">{goal?.progress || 0}%</span>
        </div>

        <div className="flex cursor-default items-center justify-start gap-3">
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

          <Tooltip content="Created on" size="sm" showArrow placement="bottom">
            <div className="flex cursor-default items-center gap-1 text-xs text-zinc-500">
              <Calendar03Icon width={16} color={undefined} />
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
    </>
  );
}
