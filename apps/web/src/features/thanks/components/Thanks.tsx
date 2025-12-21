import Image from "next/image";

import { type ToolCategory, toolCategories, tools } from "@/data/tools";
import ToolCard from "@/features/thanks/components/ToolCard";

interface ToolMetadata {
  title: string | null;
  description: string | null;
  favicon: string | null;
  website_name: string | null;
  website_image: string | null;
  url: string;
}

interface ThanksProps {
  toolsMetadata: Record<string, ToolMetadata>;
}

export default function Thanks({ toolsMetadata }: ThanksProps) {
  const toolsByCategory = toolCategories.reduce(
    (acc, category) => {
      acc[category] = tools.filter((tool) => tool.category === category);
      return acc;
    },
    {} as Record<ToolCategory, typeof tools>,
  );

  return (
    <div className="flex min-h-screen w-screen justify-center bg-black px-6 py-28">
      <div className="fixed top-0 left-0 z-0 flex h-screen w-full items-center justify-center opacity-5">
        <Image
          src="/images/logos/logo.webp"
          alt="GAIA Logo"
          className="scale-110 object-contain grayscale"
          fill
        />
      </div>

      <div className="relative w-full max-w-(--breakpoint-xl) space-y-12">
        <div className="space-y-6 text-center">
          <div className="flex w-full justify-center">
            <Image
              src="/images/logos/logo.webp"
              alt="GAIA Logo"
              width={80}
              height={80}
            />
          </div>

          <div className="space-y-4">
            <h1 className="text-4xl font-bold tracking-tight text-white md:text-5xl">
              Tools We Love
            </h1>
            <p className="mx-auto max-w-2xl text-lg font-light leading-relaxed text-foreground-500">
              GAIA is built on the shoulders of giants. This page exists to
              celebrate open-source culture and the incredible tools that make
              building great software possible. These projects inspire us daily,
              and we want to raise awareness for just how amazing they are.
            </p>
          </div>
        </div>

        <div className="space-y-12">
          {toolCategories.map((category) => {
            const categoryTools = toolsByCategory[category];
            if (!categoryTools || categoryTools.length === 0) return null;

            return (
              <section key={category} className="space-y-4">
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-semibold text-white">
                    {category}
                  </h2>
                  <span className="rounded-full bg-zinc-800 p-1 px-1.5 aspect-square flex items-center justify-center text-sm text-zinc-400 size-7">
                    {categoryTools.length}
                  </span>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
                  {categoryTools.map((tool) => (
                    <ToolCard
                      key={tool.name}
                      tool={tool}
                      metadata={toolsMetadata[tool.url]}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>

        <div className="border-t border-zinc-800 pt-12 text-center">
          <p className="text-sm text-foreground-500">
            Thank you to all the maintainers, contributors, and communities
            behind these amazing projects.
          </p>
        </div>
      </div>
    </div>
  );
}
