import { Geist_Mono } from "next/font/google";

export const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-geist-mono",
  display: "swap",
  preload: true,
});
