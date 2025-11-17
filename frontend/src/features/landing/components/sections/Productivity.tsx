// import { Tab, Tabs } from "@heroui/react";
import { Chip } from "@heroui/chip";
import Link from "next/link";
import { useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/shadcn/raised-button";
// import { CalendarDemo } from "@/features/calendar/components/Calendar";
// import GoalsStepsContent from "./GoalsStepsContent";
// import MailAnimationWrapper from "./MailAnimationWrapper";
// import TodosBentoContent from "./TodosBentoContent";
import UseCaseCard from "@/features/use-cases/components/UseCaseCard";
import { UseCase } from "@/features/use-cases/types";
import { workflowApi } from "@/features/workflows/api/workflowApi";

import LargeHeader from "../shared/LargeHeader";

export default function Productivity() {
  // const [selectedTab, setSelectedTab] = useState("email");

  const [selectedCategory, setSelectedCategory] = useState("all");
  const [useCases, setUseCases] = useState<UseCase[]>([]);

  useEffect(() => {
    const fetchUseCases = async () => {
      try {
        const resp = await workflowApi.getExploreWorkflows(50, 0);
        const converted = resp.workflows.map((w) => ({
          title: w.title,
          description: w.description,
          action_type: "workflow" as const,
          integrations:
            w.steps
              ?.map((s) => s.tool_category)
              .filter((v, i, a) => a.indexOf(v) === i) || [],
          categories: w.categories || ["featured"],
          published_id: w.id,
          slug: w.id,
          steps: w.steps,
          creator: w.creator,
        }));
        setUseCases(converted);
      } catch (error) {
        console.error("Error fetching explore workflows:", error);
      }
    };

    fetchUseCases();
  }, []);

  const allCategories = [
    "all",
    ...Array.from(new Set(useCases.flatMap((item) => item.categories || []))),
  ];

  const filteredUseCases =
    selectedCategory === "all"
      ? useCases
      : useCases.filter((useCase) =>
          useCase.categories?.includes(selectedCategory),
        );

  return (
    <div className="relative flex flex-col items-center justify-start px-4 sm:px-6">
      <div
        className="absolute -top-20 left-0 z-0 h-screen w-screen"
        style={{
          backgroundImage: `
        radial-gradient(
          circle at top left,
          #00bbff40,
          transparent 70%
        )
      `,
          filter: "blur(100px)",
          backgroundRepeat: "no-repeat",
        }}
      />

      <div className="relative z-[1] flex w-full max-w-7xl flex-col items-center justify-center p-4 sm:p-6 lg:p-7">
        <LargeHeader
          centered
          headingText="Automate your daily chaos"
          subHeadingText="Skip the grunt work forever. Create insane workflows."
        />

        <div className="mt-4 mb-4 flex flex-wrap justify-center gap-2 sm:mt-5 sm:mb-5 lg:mt-6">
          {allCategories.map((category) => (
            <Chip
              key={category as string}
              variant={selectedCategory === category ? "solid" : "flat"}
              color={selectedCategory === category ? "primary" : "default"}
              className="cursor-pointer capitalize"
              size="lg"
              onClick={() => setSelectedCategory(category as string)}
            >
              {category === "all" ? "All" : (category as string)}
            </Chip>
          ))}
        </div>

        <div className="grid max-w-7xl grid-cols-1 grid-rows-1 gap-4 sm:grid-cols-2 sm:gap-5 lg:grid-cols-3 lg:gap-6 xl:grid-cols-3">
          {filteredUseCases.slice(0, 6).map((useCase, index) => (
            <UseCaseCard
              key={useCase.published_id || index}
              title={useCase.title || ""}
              description={useCase.description || ""}
              action_type={useCase.action_type || "prompt"}
              integrations={useCase.integrations || []}
              prompt={useCase.prompt}
              slug={useCase.slug}
              steps={useCase.steps}
            />
          ))}
        </div>

        <Link href={"/use-cases"} className="mt-6 sm:mt-8 lg:mt-10">
          <RaisedButton
            className="rounded-xl text-black! before:rounded-xl hover:scale-110"
            color="#00bbff"
          >
            View all Use Cases
          </RaisedButton>
        </Link>
      </div>
    </div>
  );
}
