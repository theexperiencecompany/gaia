import type { ReactNode } from "react";

import { defaultFont, getAllFontVariables } from "@/app/fonts";

/**
 * Bare shell for the bot connect-link page. It loads none of the locale
 * layout's third-party analytics scripts, since the page holds a live
 * single-use code in its form until the user presses Continue.
 */
export default function ConnectLinkLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`${getAllFontVariables()} dark`}>
      <body className={`dark ${defaultFont.className}`}>{children}</body>
    </html>
  );
}
