import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Inter from Google Fonts (body + UI text)
const { fontFamily: interFamily } = loadInter("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export const FONT_FAMILIES = {
  inter: interFamily,
  display: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
};

export async function loadLocalFonts(): Promise<void> {
  // Anonymous Pro (monospace for typing/code contexts)
  await loadFont({
    family: "Anonymous Pro",
    url: staticFile("fonts/AnonymousPro-Regular.woff2"),
    weight: "400",
  }).catch(() => {
    // Gracefully fall back if not available
  });
}
