import localFont from "next/font/local";

export const ppEditorialNew = localFont({
  src: [
    {
      path: "./editor-new/PPEditorialNew-Ultralight.otf",
      weight: "200",
      style: "normal",
    },
    {
      path: "./editor-new/PPEditorialNew-UltralightItalic.otf",
      weight: "200",
      style: "italic",
    },
    {
      path: "./editor-new/PPEditorialNew-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./editor-new/PPEditorialNew-Italic.otf",
      weight: "400",
      style: "italic",
    },
    {
      path: "./editor-new/PPEditorialNew-Ultrabold.otf",
      weight: "800",
      style: "normal",
    },
    {
      path: "./editor-new/PPEditorialNew-UltraboldItalic.otf",
      weight: "800",
      style: "italic",
    },
  ],
  variable: "--font-pp-editorial-new",
  display: "swap",
  preload: true,
  fallback: ["serif"],
});
