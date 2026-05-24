import { useRef } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";
import { Link } from "@/i18n/navigation";
import GetStartedButton from "../shared/GetStartedButton";
import { TextSoftBlurIn } from "../shared/TextSoftBlurIn";

export default function UseCasesSectionLanding() {
  const contentRef = useRef(null);

  return (
    <div className="relative flex flex-col items-center justify-start px-4 sm:px-6 min-h-screen">
      <div className="relative z-1 flex w-full max-w-7xl flex-col items-center justify-center p-4 sm:p-6 lg:p-7 gap-10 min-h-screen">
        <TextSoftBlurIn
          text="If you do it, GAIA can automate it"
          as="h3"
          className="text-4xl font-serif font-normal!"
        />
        <div className="max-w-5xl">
          <UseCaseSection
            dummySectionRef={contentRef}
            hideUserWorkflows={true}
            useBlurEffect={true}
            rows={2}
            columns={3}
            hideAllCategory={true}
            scroller={null}
          />
        </div>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row">
          <Link href={"/use-cases"}>
            <RaisedButton
              className="rounded-xl text-black! before:rounded-xl hover:scale-105 gap-1"
              color="#00bbff"
            >
              View More
            </RaisedButton>
          </Link>
          <GetStartedButton
            btnColor="#ffffff"
            classname="px-1 hover:scale-105"
            text="Who it's for"
            href="/for"
          />
          {/* <Button variant="flat">Who it's for</Button> */}
        </div>
      </div>
    </div>
  );
}
