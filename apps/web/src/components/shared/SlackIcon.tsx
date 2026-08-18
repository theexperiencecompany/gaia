import Image from "next/image";

/**
 * Slack icon shared by the marketing persona pages (founders, agency owners,
 * product managers, sales, software developers, engineering managers).
 *
 * Rendered `unoptimized`: SVGs never route through the image optimizer —
 * see the `images` comment in next.config.mjs.
 */
export const SlackIcon = () => (
  <Image
    src="/images/icons/slack.svg"
    width={14}
    height={14}
    alt="Slack"
    unoptimized
    className="opacity-70"
  />
);
