import Link from "next/link";
import { ChevronRight } from "@/components/shared/icons";

const EDITORIAL_CARDS = [
  {
    tag: "Comparison",
    title: "GAIA vs ChatGPT — what changes when your assistant acts first",
    description:
      "ChatGPT waits for a prompt. GAIA monitors your inbox and acts before you ask.",
    href: "/compare/chatgpt",
  },
  {
    tag: "For your role",
    title: "What GAIA looks like for chiefs of staff",
    description:
      "Briefings, follow-ups, and cross-team coordination handled before your first meeting.",
    href: "/for/chiefs-of-staff",
  },
  {
    tag: "Switching",
    title: "Coming from Superhuman? Here's what's different.",
    description: "Superhuman speeds up your inbox. GAIA manages it for you.",
    href: "/alternative-to/superhuman",
  },
] as const;

export default function EditorialClose() {
  return (
    <section className="flex w-full flex-col items-center px-4 py-16 sm:px-6 sm:py-20 lg:px-8">
      <div className="flex w-full max-w-5xl flex-col gap-8">
        <h2 className="text-xl font-medium text-zinc-200">Keep reading</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {EDITORIAL_CARDS.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group flex flex-col gap-3 rounded-2xl bg-zinc-900 p-5 outline outline-1 outline-zinc-800 transition-all duration-200 hover:-translate-y-0.5 hover:outline-zinc-700"
            >
              <span className="text-[10px] font-semibold uppercase tracking-widest text-primary">
                {card.tag}
              </span>
              <h3 className="text-sm font-medium leading-snug text-zinc-100 group-hover:text-white">
                {card.title}
              </h3>
              <p className="text-xs leading-relaxed text-zinc-500">
                {card.description}
              </p>
              <span className="mt-auto flex items-center gap-1 text-xs text-zinc-500 group-hover:text-zinc-300 transition-colors">
                Read <ChevronRight width={12} height={12} />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
