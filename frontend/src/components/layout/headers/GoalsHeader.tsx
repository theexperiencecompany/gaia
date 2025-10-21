"use client";

import { useState } from "react";

import { SidebarHeaderButton } from "@/components/layout/headers/HeaderManager";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { Target04Icon, Target02Icon } from "@/components/shared/icons";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import AddGoalDialog from "@/features/goals/components/AddGoalDialog";
import { useGoals } from "@/features/goals/hooks/useGoals";
import { useRouter } from "next/navigation";

export default function GoalsHeader() {
  const [openDialog, setOpenDialog] = useState(false);
  const { createGoal } = useGoals();
  const router = useRouter();

  const handleAddGoal = async (goalTitle: string) => {
    try {
      const newGoal = await createGoal({ title: goalTitle });
      router.push(`/goals/${newGoal.id}`);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <>
      <div className="flex w-full items-center justify-between">
        <HeaderTitle
          icon={<Target02Icon width={20} height={20} color={undefined} />}
          text="Goals"
        />

        <div className="relative z-[100] flex items-center">
          <SidebarHeaderButton
            aria-label="Create new goal"
            tooltip="Create new goal"
            onClick={() => setOpenDialog(true)}
          >
            <Target04Icon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
          <NotificationCenter />
        </div>
      </div>
      <AddGoalDialog
        addGoal={handleAddGoal}
        openDialog={openDialog}
        setOpenDialog={setOpenDialog}
        prevGoalTitle={null}
      />
    </>
  );
}
