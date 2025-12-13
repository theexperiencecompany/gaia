import MemoryGraphDemo from "../demo/MemoryGraphDemo";
import { ContentSection } from "../shared/ContentSection";
import LargeHeader from "../shared/LargeHeader";

export default function Personalised() {
  return (
    <div className="flex h-fit min-h-screen flex-col items-center justify-center gap-6 px-4 sm:gap-8 sm:px-6 lg:gap-10 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col gap-8 p-4 sm:gap-10 sm:p-6 lg:gap-12 lg:p-7">
        <LargeHeader
          // centered
          headingText="Finally, AI that feels like it's made for you"
          chipText="Truly Personalised"
          subHeadingText="Stop repeating yourself. Start building a smarter, personal AI."
        />

        <div className="grid w-full max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 sm:gap-8 lg:gap-10">
          <div className="rounded-3xl bg-zinc-900">
            <MemoryGraphDemo />
          </div>

          <ContentSection
            title="Graph Memory"
            description={`GAIA uses a graph-based memory system that actually understands how your life connects. Tasks link to projects. Meetings link to documents. Emails link to people and decisions. Instead of dumping information into a flat list, GAIA builds a living map of everything you're working on. This makes recall instant and context automatic. When you ask for something, GAIA already knows the relationships around it, so the answers feel accurate and grounded. It is faster, more reliable, and a lot closer to how humans actually remember things.`}
          />

          <ContentSection
            title="Feels Familiar, Not Robotic"
            description="GAIA doesn't talk like a corporate chatbot or a motivational speaker. It responds like a helpful teammate who gets your pace and preferences. Nothing extra. Nothing cringe. Just clarity."
          />
          <ContentSection
            title="Gets Sharper With Every Task"
            description={`The more you use GAIA for mail, tasks, scheduling, research, or planning, the smarter and more useful it becomes. You don't "train" GAIA. You live your life. GAIA learns naturally.`}
          />
        </div>

        {/* <div className="mx-auto grid w-full max-w-4xl grid-cols-1 grid-rows-1 justify-between gap-4 py-6 sm:gap-6 sm:py-8 lg:grid-cols-2 lg:gap-7 lg:py-10">
          <BentoItem
            title="Recall Everything Instantly"
            description="GAIA remembers every detail you mention in a conversation"
          >
            <div className="flex w-full flex-col gap-2">
              <SimpleChatBubbleUser className2="mb-2">
                What do you know about me?
              </SimpleChatBubbleUser>
              {personalInfo.map((info, index) => (
                <div
                  key={index}
                  className="mr-2 flex gap-1 rounded-xl bg-zinc-700 px-2 py-1.5 text-xs sm:mr-4 sm:gap-2 sm:rounded-2xl sm:px-3 sm:py-2 sm:text-sm lg:mr-7 lg:px-4 lg:text-base"
                >
                  <AiBrain01Icon className="relative top-0.5 h-3 w-3 flex-shrink-0 text-zinc-400 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
                  <div className="w-full">{info}</div>
                </div>
              ))}
            </div>
          </BentoItem>

          <BentoItem
            title="Build a Knowledge Graph"
            description="Builds intelligent bridges between your scattered memories"
            childrenClassName="p-0 overflow-hidden"
          >
            <MemoryGraphDemo />
          </BentoItem>
        </div> */}
      </div>
    </div>
  );
}
