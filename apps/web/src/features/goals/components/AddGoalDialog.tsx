import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import type React from "react";
import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

import { SentIcon } from "@/icons";
import { posthog } from "@/lib";

export default function AddGoalDialog({
  openDialog,
  setOpenDialog,
  addGoal,
  prevGoalTitle,
}: {
  openDialog: boolean;
  setOpenDialog: Dispatch<SetStateAction<boolean>>;
  addGoal: (goal: string) => void;
  prevGoalTitle?: string | null;
}) {
  const [goalTitle, setGoalTitle] = useState(prevGoalTitle || "");

  useEffect(() => {
    if (prevGoalTitle) setGoalTitle(prevGoalTitle);
  }, [prevGoalTitle]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleAddGoal();
    }
  };

  const handleAddGoal = () => {
    if (!goalTitle) {
      return;
    }

    // Track goal creation
    posthog.capture("goals:created", {
      title_length: goalTitle.length,
      has_previous_title: !!prevGoalTitle,
    });

    addGoal(goalTitle);
    setGoalTitle("");
    setOpenDialog(false);
  };

  return (
    <Modal
      backdrop="blur"
      className="text-foreground"
      isOpen={openDialog}
      onOpenChange={setOpenDialog}
    >
      <ModalContent>
        <ModalHeader className="mb-0 flex flex-col gap-1 pb-0">
          Add Goal
        </ModalHeader>
        <ModalBody>
          <div className="text-sm">
            I will help you create a step-by-step plan to achieve your goal !
          </div>
          <Input
            classNames={{ inputWrapper: "pr-2" }}
            endContent={
              <Button
                isIconOnly
                className="font-medium text-foreground-800"
                color="primary"
                onPress={handleAddGoal}
              >
                <SentIcon />
              </Button>
            }
            label="What goal do you want to achieve?"
            value={goalTitle}
            variant="faded"
            autoFocus
            onChange={(e: { target: { value: SetStateAction<string> } }) =>
              setGoalTitle(e.target.value)
            }
            onKeyDown={handleKeyPress}
          />
        </ModalBody>
        <ModalFooter className="pt-0" />
      </ModalContent>
    </Modal>
  );
}
