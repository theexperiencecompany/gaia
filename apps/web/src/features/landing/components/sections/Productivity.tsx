// import { Tab, Tabs } from "@heroui/react";

import Link from "next/link";
import { useRef } from "react";
import { ChevronRight } from "@/components";
import { RaisedButton } from "@/components/ui/raised-button";
// import { CalendarDemo } from "@/features/calendar/components/Calendar";
// import GoalsStepsContent from "./GoalsStepsContent";
// import MailAnimationWrapper from "./MailAnimationWrapper";
// import TodosBentoContent from "./TodosBentoContent";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";

export default function UseCasesSectionLanding() {
  const contentRef = useRef(null);

  return (
    <div className="relative flex flex-col items-center justify-start px-4 sm:px-6 min-h-screen">
      {/* <div
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
      /> */}

      <div className="relative z-1 flex w-full max-w-7xl flex-col items-center justify-center p-4 sm:p-6 lg:p-7 gap-10 min-h-screen">
        {/* <LargeHeader
          centered
          headingText="Here's a few things GAIA can do for you"
          subHeadingText="Skip the grunt work forever. Create insane workflows."
        /> */}
        <h3 className="text-4xl font-serif font-normal!">
          Here's a few things GAIA can do for you
        </h3>
        <div className="max-w-5xl">
          <UseCaseSection
            dummySectionRef={contentRef}
            hideUserWorkflows={true}
            useBlurEffect={true}
            rows={2}
            columns={3}
            hideAllCategory={true}
          />
        </div>
        <Link href={"/use-cases"} className="mt-2">
          <RaisedButton
            className="rounded-xl text-black! before:rounded-xl hover:scale-110 gap-1"
            color="#00bbff"
          >
            View all Use Cases
            <ChevronRight width={18} height={18} />
          </RaisedButton>
        </Link>
      </div>
    </div>
  );
}
