# pptxgenjs reference

`read` this when adapting `deck.mjs`. The template is a Node ES module that builds a deck and writes it to the path passed as `process.argv[2]`.

## Skeleton
```js
import pptxgen from "pptxgenjs";
const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE"; // 13.33in x 7.5in widescreen

const slide = pptx.addSlide();
slide.addText("Hello", { x: 0.5, y: 0.5, w: 12.3, h: 1, fontSize: 32, bold: true });

const out = process.argv[2] || "out.pptx";
await pptx.writeFile({ fileName: out });
```

## Units & grid
- All positions/sizes are in **inches**. Widescreen slide = **13.33 wide × 7.5 tall**.
- A safe content area: `x: 0.5 .. 12.8`, `y: 0.5 .. 7.0`.

## Building blocks
- **Text:** `slide.addText("...", { x, y, w, h, fontSize, bold, color: "333333", align: "left" })`.
- **Bulleted text:** pass an array of objects:
  ```js
  slide.addText(
    [{ text: "Point one", options: { bullet: true } },
     { text: "Point two", options: { bullet: true } }],
    { x: 0.7, y: 1.6, w: 12, h: 4, fontSize: 18 }
  );
  ```
- **Background:** `slide.background = { color: "1A4D8F" };`
- **Shape:** `slide.addShape(pptx.ShapeType.rect, { x, y, w, h, fill: { color: "EEEEEE" } });`
- **Table:** `slide.addTable(rows, { x, y, w, fontSize, border: { pt: 0.5, color: "CCCCCC" } });` where `rows` is an array of arrays of cell strings/objects.
- **Native chart:**
  ```js
  slide.addChart(pptx.ChartType.bar,
    [{ name: "Revenue", labels: ["Q1","Q2","Q3"], values: [1.0, 1.2, 1.5] }],
    { x: 0.7, y: 1.6, w: 12, h: 5, showLegend: true });
  ```
  Types: `pptx.ChartType.bar | line | pie | area | doughnut`.
- **Image:** `slide.addImage({ path: "logo.png", x, y, w, h });` (path relative to the program).

## Common error → fix
| Error contains | Cause | Fix |
| --- | --- | --- |
| `Cannot find module 'pptxgenjs'` | toolchain not installed | re-run the build script |
| `addText is not a function` | called on `pptx`, not a slide | call on the result of `pptx.addSlide()` |
| text runs off the slide | x+w exceeds 13.33 / too many bullets | shrink `w`, fewer bullets, split the slide |
| empty file | missing `await pptx.writeFile(...)` | keep the final `await writeFile` |
