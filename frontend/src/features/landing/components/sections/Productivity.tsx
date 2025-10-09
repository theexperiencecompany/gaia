// import { Tab, Tabs } from "@heroui/react";
import { Chip } from "@heroui/chip";
import Link from "next/link";
import { useState } from "react";

import { RaisedButton } from "@/components/ui/shadcn/raised-button";
// import { CalendarDemo } from "@/features/calendar/components/Calendar";
// import GoalsStepsContent from "./GoalsStepsContent";
// import MailAnimationWrapper from "./MailAnimationWrapper";
// import TodosBentoContent from "./TodosBentoContent";
import UseCaseCard from "@/features/use-cases/components/UseCaseCard";
import dataJson from "@/features/use-cases/constants/data.json";

import LargeHeader from "../shared/LargeHeader";
import WorkflowSection from "./WorkflowSection";

interface UseCase {
  title: string;
  description: string;
  prompt: string;
  published_id: string;
  integrations: string[];
  categories: string[];
  demo_type?: string;
  demo_content?: string;
  featured?: boolean;
  action_type: "prompt" | "workflow";
}

interface UseCaseData {
  templates: UseCase[];
}

export default function Productivity() {
  // const [selectedTab, setSelectedTab] = useState("email");

  const [selectedCategory, setSelectedCategory] = useState("all");

  const data = dataJson as UseCaseData;

  const allCategories = [
    "all",
    ...Array.from(
      new Set(data.templates.flatMap((item) => item.categories || [])),
    ),
  ];

  const filteredUseCases =
    selectedCategory === "all"
      ? data.templates
      : data.templates.filter((useCase) =>
          useCase.categories?.includes(selectedCategory),
        );

  return (
    <div className="relative flex flex-col items-center justify-start overflow-hidden px-4 sm:px-6">
      <div className="relative z-[1] flex w-full max-w-7xl flex-col items-center justify-center p-4 py-20 sm:p-6 sm:py-28 lg:p-7 lg:py-36">
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
      <WorkflowSection />
    </div>
  );
}
