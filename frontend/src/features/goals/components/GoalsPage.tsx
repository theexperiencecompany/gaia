"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import AddGoalDialog from "@/features/goals/components/AddGoalDialog";
import { GoalCard } from "@/features/goals/components/GoalCard";
import { useGoals } from "@/features/goals/hooks/useGoals";

const allGoalSuggestions = [
  // Technical & Creative Projects
  "Build and launch a habit tracker app",
  "Create a personal blog and publish 10 posts",
  "Build a Chrome extension and list it on the Web Store",
  "Learn React by cloning a to-do app",
  "Deploy a REST API and connect it to a frontend",
  "Build a resume website with animations",
  "Create a PDF summarizer using OpenAI",
  "Publish your first open-source library on GitHub",
  "Learn basic Python and automate a task",
  "Launch a side project MVP in 30 days",

  // Wellness & Mindfulness
  "Meditate daily for 30 days",
  "Sleep 8 hours for 2 weeks straight",
  "Practice gratitude journaling every night",
  "Complete a 7-day no-phone challenge",
  "Finish a 30-day yoga or stretch challenge",
  "Go on 3 nature walks in a week",
  "Take one weekend off for complete rest",
  "Practice digital detox every Sunday",

  // Productivity & Self-Improvement
  "Plan each week using a weekly planner",
  "Create a personal OKR system and track it",
  "Implement GTD or PARA in Notion",
  "Design your daily routine and follow it for 14 days",
  "Build a personal knowledge base system",
  "Do a monthly review and set 3 priorities",
  "Create a deep work ritual and do it 3x/week",

  // Finance & Career Growth
  "Track all expenses for 30 days",
  "Build a personal finance tracker in a spreadsheet",
  "Save ₹10,000/month for 3 months",
  "Update your resume and portfolio",
  "Apply to 5 jobs you're excited about",
  "Set up a passive income source",
  "Freelance and earn your first ₹5,000",

  // Lifestyle & Personal Expression
  "Start a photography challenge: 1 photo a day",
  "Cook at home 5 days a week",
  "Read 3 non-fiction books in 2 months",
  "Plan and take a solo trip",
  "Create and publish a YouTube video",
  "Journal every day for a week",
  "Declutter your room and donate unused items",
];

function shuffleArray<T>(array: T[]): T[] {
  const arr = [...array];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export default function GoalsPage() {
  const [prevGoalTitle, setPrevGoalTitle] = useState<string | null>(null);
  const [openDialog, setOpenDialog] = useState(false);
  const router = useRouter();

  const { goals, loading, fetchGoals, createGoal } = useGoals();

  useEffect(() => {
    fetchGoals();
  }, [fetchGoals]);

  const handleAddGoal = async (goalTitle: string) => {
    try {
      const newGoal = await createGoal({ title: goalTitle });
      router.push(`/goals/${newGoal.id}`);
    } catch (err) {
      // Error is already handled in the hook
      console.error(err);
    }
  };

  const shuffledGoals = shuffleArray(allGoalSuggestions).slice(0, 5);

  return (
    <>
      <div className="flex h-full w-full flex-col justify-between p-5">
        <div className="w-full overflow-y-auto">
          {goals.length > 0 ? (
            <div className="grid grid-cols-1 justify-center gap-4 px-1 pb-28 sm:grid-cols-1 sm:px-16 md:grid-cols-2 lg:grid-cols-3">
              {goals.map((goal, index) => (
                <GoalCard key={index} fetchGoals={fetchGoals} goal={goal} />
              ))}
            </div>
          ) : (
            <div className="flex h-[70vh] w-full items-center justify-center">
              {loading ? <Spinner /> : <div>No Goals created yet.</div>}
            </div>
          )}
        </div>
        <div className="absolute bottom-6 left-0 z-10 flex w-full flex-col items-center justify-center gap-4">
          {
            <div className="flex max-w-(--breakpoint-lg) flex-wrap justify-center gap-2">
              {shuffledGoals.map((suggestion, index) => (
                <Chip
                  key={index}
                  variant="flat"
                  color="primary"
                  className="cursor-pointer text-primary"
                  onClick={() => {
                    setPrevGoalTitle(suggestion);
                    setOpenDialog(true);
                  }}
                >
                  {suggestion}
                </Chip>
              ))}
            </div>
          }
          <Button
            className="gap-2 font-semibold"
            color="primary"
            onPress={() => setOpenDialog(true)}
          >
            Create a new Goal
          </Button>
        </div>
        <div className="bg-custom-gradient2 absolute bottom-0 left-0 z-1 h-[100px] w-full" />
      </div>
      <AddGoalDialog
        addGoal={handleAddGoal}
        openDialog={openDialog}
        setOpenDialog={setOpenDialog}
        prevGoalTitle={prevGoalTitle}
      />
    </>
  );
}
