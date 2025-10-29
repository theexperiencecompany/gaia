import { Instrument_Serif } from "next/font/google";

export const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400", // Instrument Serif only has one weight (400)
  variable: "--font-instrument-serif",
  display: "swap",
  preload: true,
  style: "normal", // or "italic" for the italic variant
});
