import { loadFont } from "@remotion/fonts";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { continueRender, delayRender, staticFile } from "remotion";

// Inter from Google Fonts (body + UI text)
const { fontFamily: interFamily } = loadInter("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export const FONT_FAMILIES = {
  inter: interFamily,
  display: '"Aeonik", "Helvetica Neue", Helvetica, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
};

const waitForFonts = delayRender("Loading local fonts");

Promise.all([
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Bold.otf"),
    weight: "700",
  }),
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Black.otf"),
    weight: "900",
  }),
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Air.otf"),
    weight: "400",
  }),
  loadFont({
    family: "Anonymous Pro",
    url: staticFile("fonts/AnonymousPro-Regular.woff2"),
    weight: "400",
  }),
])
  .then(() => continueRender(waitForFonts))
  .catch((err) => {
    console.error("Font loading failed:", err);
    continueRender(waitForFonts);
  });
