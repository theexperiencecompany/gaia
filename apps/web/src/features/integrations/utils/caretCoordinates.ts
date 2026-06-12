// Pixel coordinates of the caret inside a <textarea>, via the mirror-div
// technique (a hidden div that copies the textarea's box + typography, with the
// text up to the caret, then we measure a marker span). Adapted from the
// well-known `textarea-caret-position` algorithm (Component, MIT).

const MIRRORED_PROPERTIES = [
  "boxSizing",
  "width",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontStyle",
  "fontVariant",
  "fontWeight",
  "fontStretch",
  "fontSize",
  "lineHeight",
  "fontFamily",
  "textAlign",
  "textTransform",
  "textIndent",
  "letterSpacing",
  "wordSpacing",
  "tabSize",
];

export interface CaretCoordinates {
  top: number;
  left: number;
  height: number;
}

export const getCaretCoordinates = (
  el: HTMLTextAreaElement,
  position: number,
): CaretCoordinates => {
  const div = document.createElement("div");
  document.body.appendChild(div);

  const computed = getComputedStyle(el);
  const style = div.style as unknown as Record<string, string>;
  const source = computed as unknown as Record<string, string>;

  style.position = "absolute";
  style.visibility = "hidden";
  style.whiteSpace = "pre-wrap";
  style.wordWrap = "break-word";
  style.overflow = "hidden";
  for (const prop of MIRRORED_PROPERTIES) {
    style[prop] = source[prop];
  }

  div.textContent = el.value.slice(0, position);
  const marker = document.createElement("span");
  // A non-empty span so it has a measurable box even at the very end.
  marker.textContent = el.value.slice(position) || ".";
  div.appendChild(marker);

  const lineHeight =
    Number.parseFloat(computed.lineHeight) ||
    Number.parseFloat(computed.fontSize) * 1.2;
  const coords: CaretCoordinates = {
    top: marker.offsetTop + Number.parseInt(computed.borderTopWidth, 10),
    left: marker.offsetLeft + Number.parseInt(computed.borderLeftWidth, 10),
    height: lineHeight,
  };

  div.remove();
  return coords;
};
