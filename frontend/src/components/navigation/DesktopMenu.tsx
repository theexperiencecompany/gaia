import { Button } from "@heroui/button";
import { StarFilledIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { appConfig } from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";
import { useGitHubStars } from "@/hooks/useGitHubStars";

import { Github } from "../shared";

export default function DesktopMenu({ scrolled }: { scrolled: boolean }) {
  const user = useUser();
  const isAuthenticated = user?.email; // Check if user has email to determine auth status
  const { data: repoData, isLoading: isLoadingStars } = useGitHubStars(
    "theexperiencecompany/gaia",
  );

  if (scrolled) {
    return (
      <div className="flex gap-6">
        {/* Auth Buttons */}
        <div className="flex items-center gap-2">
          <div className="relative top-1">
            <Button
              as={Link}
              href="https://github.com/theexperiencecompany/gaia"
              target="_blank"
              size="sm"
              rel="noopener noreferrer"
              variant="faded"
              startContent={<Github width={18} />}
              className="pr-0.5"
              endContent={
                <div className="flex flex-nowrap gap-1 rounded-sm bg-zinc-900 p-1 px-2 text-white">
                  {isLoadingStars ? "..." : repoData?.stargazers_count || 0}
                  <StarFilledIcon />
                </div>
              }
            >
              Star
            </Button>
          </div>

          {isAuthenticated ? (
            // Show auth links that require login
            appConfig.links.auth
              .filter((link) => link.requiresAuth)
              .map((link) => (
                <Button
                  key={link.href}
                  as={Link}
                  className="font-medium"
                  color="primary"
                  endContent={link.icon}
                  radius="lg"
                  size="md"
                  href={link.href}
                >
                  {link.label}
                </Button>
              ))
          ) : (
            <>
              {appConfig.links.auth
                .filter((link) => link.guestOnly)
                .map((link) => (
                  <Button
                    key={link.href}
                    as={Link}
                    className="p-0 px-4 text-sm font-medium"
                    color={link.href === "/signup" ? "primary" : "default"}
                    size="sm"
                    href={link.href}
                    variant={link.href === "/signup" ? "solid" : "light"}
                  >
                    {link.label}
                  </Button>
                ))}
            </>
          )}
        </div>
      </div>
    );
  }

  return null;
}
