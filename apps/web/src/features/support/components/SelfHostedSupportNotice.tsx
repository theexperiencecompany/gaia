import { Link } from "@heroui/link";
import { Github01Icon } from "@icons";

import {
  GAIA_GITHUB_DISCUSSIONS_URL,
  GAIA_GITHUB_ISSUES_URL,
} from "../constants/supportConstants";

/** Shown instead of the support form on a self-hosted instance, whose requests never reach GAIA. */
export function SelfHostedSupportNotice() {
  return (
    <div className="flex flex-col gap-3 text-sm text-zinc-400">
      <p>
        This GAIA is self-hosted, so requests sent from here don&apos;t reach
        the GAIA team. For help with this instance, ask its administrator.
      </p>
      <p>Report bugs and request features on GitHub instead.</p>
      <div className="flex flex-wrap gap-4">
        <Link href={GAIA_GITHUB_ISSUES_URL} isExternal showAnchorIcon size="sm">
          <Github01Icon width={14} height={14} className="mr-1" />
          Open an issue
        </Link>
        <Link
          href={GAIA_GITHUB_DISCUSSIONS_URL}
          isExternal
          showAnchorIcon
          size="sm"
        >
          <Github01Icon width={14} height={14} className="mr-1" />
          Start a discussion
        </Link>
      </div>
    </div>
  );
}
