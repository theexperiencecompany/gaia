import type { ReactNode } from "react";
import FAQAccordion from "@/components/seo/FAQAccordion";
import InlineCode from "@/components/ui/InlineCode";
import { isSelfhostWeb } from "@/lib/selfhost";
import { BOT_COMMAND_GROUPS, BOTS_FAQS } from "../pageContent";

function GuideSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl bg-zinc-900/50 p-6 sm:p-8">
      <h2 className="mb-5 font-serif text-3xl font-medium text-white">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** How linking works, the everyday commands and the FAQ, below the bot cards. */
export default function BotsGuide() {
  return (
    <div className="flex flex-col gap-6">
      <GuideSection title="Link your account">
        <p className="leading-relaxed text-zinc-400">
          Send <InlineCode>/auth</InlineCode> in a chat with GAIA. It replies
          with a one-time link that expires in 10 minutes. Open it, sign in, and
          that chat is connected to your GAIA account. Send{" "}
          <InlineCode>/unlink</InlineCode> to disconnect.
          {!isSelfhostWeb() && " Chatting through the bots needs GAIA Pro."}
        </p>
      </GuideSection>

      <GuideSection title="Commands">
        <dl className="divide-y divide-zinc-800">
          {BOT_COMMAND_GROUPS.map((group) => (
            <div
              key={group.description}
              className="grid gap-2 py-3 sm:grid-cols-[180px_1fr] sm:gap-6"
            >
              <dt className="flex flex-wrap gap-2">
                {group.commands.map((command) => (
                  <InlineCode key={command}>{command}</InlineCode>
                ))}
              </dt>
              <dd className="text-zinc-300">{group.description}</dd>
            </div>
          ))}
        </dl>
      </GuideSection>

      <GuideSection title="Questions">
        <FAQAccordion faqs={BOTS_FAQS} />
      </GuideSection>
    </div>
  );
}
