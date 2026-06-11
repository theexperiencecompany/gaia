import localFont from "next/font/local";

export const aeonik = localFont({
  src: [
    {
      path: "./aeonik/AeonikExtendedProTRIAL-SemiBold.woff2",
      weight: "600",
      style: "normal",
    },
    {
      path: "./aeonik/AeonikExtendedPro-Bold.woff2",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-aeonik",
  display: "swap",
  preload: true,
  fallback: ["system-ui", "sans-serif"],
});
