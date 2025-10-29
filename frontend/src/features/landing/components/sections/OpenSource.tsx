import { Avatar, AvatarGroup } from "@heroui/avatar";
import { StarFilledIcon } from "@radix-ui/react-icons";
import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { lazy, Suspense, useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/shadcn/raised-button";
import { useGitHubContributors } from "@/hooks/useGitHubContributors";

import LargeHeader from "../shared/LargeHeader";

// Import the GitHubContributor type
interface GitHubContributor {
  login: string;
  id: number;
  avatar_url: string;
  html_url: string;
  contributions: number;
  type?: string;
}

// Lazy load the contributors section when it comes into view
const LazyContributors = lazy(() =>
  Promise.resolve({
    default: ({
      contributors,
      totalCount,
    }: {
      contributors: GitHubContributor[];
      totalCount: number;
    }) => (
      <AvatarGroup
        isBordered
        max={contributors.length}
        renderCount={() => (
          <p className="ms-2 text-small font-medium text-foreground">
            +{totalCount - contributors.length} others
          </p>
        )}
        total={contributors.length}
      >
        {contributors.map((contributor) => (
          <Avatar
            key={contributor.login}
            src={contributor.avatar_url}
            name={contributor.login}
            as={Link}
            href={contributor.html_url}
            target="_blank"
            className="cursor-pointer transition-transform hover:scale-110"
          />
        ))}
      </AvatarGroup>
    ),
  }),
);

export default function OpenSource() {
  const [isVisible, setIsVisible] = useState(false);
  const {
    data: contributorsData,
    isLoading,
    isError,
  } = useGitHubContributors("heygaia/gaia");

  const contributors = contributorsData?.contributors || [];
  const totalCount = contributorsData?.totalCount || 0;

  // Use Intersection Observer to load contributors only when section is visible
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setIsVisible(true);
        }
      },
      { threshold: 0.1 },
    );

    const section = document.getElementById("opensource-section");
    if (section) {
      observer.observe(section);
    }

    return () => observer.disconnect();
  }, []);
  return (
    <div
      id="opensource-section"
      className="flex flex-col items-center justify-center gap-10 px-4 sm:px-6 lg:px-8"
    >
      <div className="flex w-full max-w-7xl flex-col items-center justify-center rounded-2xl bg-gradient-to-b from-zinc-900 to-zinc-950 p-6 outline-1 outline-zinc-900 sm:rounded-3xl sm:p-8 lg:rounded-4xl lg:p-10">
        <LargeHeader
          headingText="Open-Source & Self-Hostable"
          subHeadingText="GAIA is fully open source. Self-host it on your own infrastructure, or explore the community-driven codebase on GitHub!"
          centered
        />
        <div className="flex -space-x-8 sm:-space-x-12 lg:-space-x-16">
          <Image
            src={"/images/icons/docker3d.webp"}
            alt="Docker Logo"
            width={200}
            height={200}
            className="relative z-[1] h-24 w-24 -rotate-10 sm:h-32 sm:w-32 lg:h-48 lg:w-48 xl:h-[200px] xl:w-[200px]"
          />
          <Image
            src={"/images/icons/github3d.webp"}
            alt="Docker Logo"
            width={200}
            className="relative z-[2] h-24 w-24 rotate-3 sm:h-32 sm:w-32 lg:h-48 lg:w-48 xl:h-[200px] xl:w-[200px]"
            height={200}
          />
        </div>

        {/* Contributors Section */}
        <div className="flex flex-col items-center gap-3 pt-4 sm:gap-4 sm:pt-6">
          <h3 className="text-center text-base font-medium text-zinc-300 sm:text-lg">
            Built by the community
          </h3>
          {isLoading ? (
            <div className="flex items-center gap-2">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-600 border-t-white sm:h-8 sm:w-8"></div>
              <span className="text-sm text-zinc-400 sm:text-base">
                Loading contributors...
              </span>
            </div>
          ) : isError ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-400 sm:text-base">
                Failed to load contributors
              </span>
            </div>
          ) : isVisible ? (
            <Suspense
              fallback={
                <div className="flex items-center gap-2">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-600 border-t-white sm:h-8 sm:w-8"></div>
                  <span className="text-sm text-zinc-400 sm:text-base">
                    Loading contributors...
                  </span>
                </div>
              }
            >
              <LazyContributors
                contributors={contributors}
                totalCount={totalCount}
              />
            </Suspense>
          ) : (
            <div className="h-8 w-full sm:h-12" /> // Placeholder to maintain layout
          )}
          {!isLoading && !isError && (
            <p className="text-center text-xs text-zinc-400 sm:text-sm">
              {totalCount} amazing contributors and growing!
            </p>
          )}
        </div>
        <div className="flex w-full flex-col gap-3 pt-6 sm:w-auto sm:flex-row sm:pt-8 lg:pt-10">
          <Link href={"https://docs.heygaia.io"} className="w-full sm:w-auto">
            <RaisedButton
              className="w-full justify-center rounded-xl text-white! before:rounded-xl hover:scale-110 sm:w-auto"
              color="#292929"
            >
              Read Docs
              <ArrowRight width={15} />
            </RaisedButton>
          </Link>
          <Link
            href={"https://github.com/heygaia/gaia"}
            className="w-full sm:w-auto"
          >
            <RaisedButton
              className="w-full justify-center rounded-xl text-black! before:rounded-xl hover:scale-110 sm:w-auto"
              color="#00bbff"
            >
              Star on GitHub <StarFilledIcon width={17} height={17} />
            </RaisedButton>
          </Link>
        </div>
      </div>
    </div>
  );
}
