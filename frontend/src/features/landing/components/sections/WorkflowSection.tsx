import { ContentSection } from "../shared/ContentSection";

export default function WorkflowSection() {
  return (
    <div className="relative mx-auto mb-20 flex min-h-screen w-full max-w-7xl flex-col justify-center p-4 px-4 sm:p-6 sm:px-6 lg:p-7 lg:px-8">
      <div className="mb-2 text-xl font-light text-primary sm:text-2xl">
        Your Daily Life, Automated
      </div>
      <div className="mb-4 font-serif text-6xl font-normal sm:mb-5">
        Simple workflows to eliminate repetitive tasks
      </div>

      <div className="mt-4 flex flex-col gap-4">
        <div className="grid w-full grid-cols-1 grid-rows-3 gap-6 sm:grid-cols-2 sm:gap-8 lg:gap-10">
          <div className="row-span-3 space-y-10">
            <ContentSection
              title="Wait, what even are workflows?"
              description="Think of them as little robots you train to do your repetitive stuff. Could be as basic as 'forward all receipts to my accountant' or as wild as 'watch my calendar, research everyone I'm meeting today, write briefing docs, and email them to me an hour before.' If you're a student, use them for tracking assignments, organizing research papers, or prepping for exams. If you're building a startup, automate investor updates, customer onboarding, or market research. Honestly, if it's something you do more than once, you can probably make a workflow for it. The more apps you connect and triggers you set up, the more powerful it gets. We're just getting started."
            />

            <ContentSection
              title="Powered by Your Todos"
              description="Every todo you add becomes its own mini-workflow. GAIA doesn't just remind you about it, it actually does the work. Research? Done. Drafting? Done. Scheduling? Done. Your todo list stops being a guilt trip and starts being your secret weapon."
            />
          </div>

          <ContentSection
            title="Smart Triggers"
            description="Set it to run every morning at 9 AM, trigger it manually when you need it, or let it kick in automatically when something happens, like when you get an email, a Slack message pops up, or your next meeting's about to start. We're constantly adding new ways to trigger your workflows based on what you tell us you need."
          />

          <ContentSection
            title="Proactive by Nature"
            description="Assignment due next week? GAIA's already researched it, created the Google Doc, and drafted it. That investor email you've been putting off? Already written and sitting in your drafts. GAIA doesn't wait around, it just handles it. Labels your emails, organizes your files, and prepares whatever you need way ahead of time."
          />

          <ContentSection
            title="Seamless Orchestration"
            description="Gmail, Google Docs, Slack, Calendar, they all talk to each other now. One workflow can pull info from your email, create a doc, schedule a meeting, and ping your team on Slack. No more tab-switching hell. Complex stuff becomes simple when everything just... works together."
          />
        </div>
      </div>

      {/* <div className="grid w-full max-w-7xl grid-cols-1 grid-rows-1 justify-between gap-4 sm:gap-6 lg:grid-cols-4 lg:gap-7">
        <BentoItem
          title="Smart Triggers"
          description="Set conditions once, automate actions forever."
        >
          <div className="flex w-full flex-col items-center justify-center gap-2 px-1 sm:gap-3">
            {triggers.map((trigger, index) => (
              <div
                key={index}
                className={`flex w-full items-center gap-2 rounded-xl bg-zinc-800 p-2 sm:gap-3 sm:rounded-2xl sm:p-3`}
              >
                <Image
                  src={trigger.icon}
                  alt={trigger.title}
                  className="h-6 w-6 sm:h-8 sm:w-8"
                  width={32}
                  height={32}
                />
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-white sm:text-base">
                    {trigger.title}
                  </span>
                  <span className="text-xs text-zinc-300 sm:text-sm">
                    {trigger.description}
                  </span>
                </div>
              </div>
            ))}
            <Chip
              color="primary"
              variant="flat"
              className="mt-1 text-xs text-primary sm:mt-2 sm:text-sm"
            >
              Automatically run workflows on triggers
            </Chip>
          </div>
        </BentoItem>
        <BentoItem
          title="Proactive by Nature"
          description="GAIA acts before you ask, preparing what you need when you need it."
          childrenClassName="p-0!"
        >
          <DotLottieReact
            src="/animations/proactive.lottie"
            loop
            autoplay
            speed={0.5}
            // playOnHover
          />
        </BentoItem>
        <BentoItem
          title="Seamless Orchestration"
          description="Makes all your apps work together like a single tool, through a unified interface."
        >
          <DotLottieReact
            src="/animations/seamless.json"
            loop
            autoplay
            speed={0.7}
            playOnHover
          />
        </BentoItem>{" "}
      </div> */}
    </div>
  );
}
