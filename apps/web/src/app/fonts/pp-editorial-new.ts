import localFont from "next/font/local";

export const ppEditorialNew = localFont({
  src: [
    {
      path: "./editor-new/PPEditorialNew-Ultralight.woff2",
      weight: "200",
      style: "normal",
    },
    {
      path: "./editor-new/PPEditorialNew-UltralightItalic.woff2",
      weight: "200",
      style: "italic",
    },
    {
      path: "./editor-new/PPEditorialNew-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./editor-new/PPEditorialNew-Italic.woff2",
      weight: "400",
      style: "italic",
    },
  ],
  variable: "--font-pp-editorial-new",
  display: "swap",
  preload: true,
  fallback: ["serif"],
});
