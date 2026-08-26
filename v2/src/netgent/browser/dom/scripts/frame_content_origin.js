// The top-left corner of an <iframe>'s CONTENT box in its parent's viewport: border-box
// left/top plus border and padding — the origin of the child document's coordinates.
// Puppeteer's #getTopLeftCornerOfFrame (puppeteer-core api/ElementHandle.ts:1380-1415).
//
// Bare function expression after the leading `//` lines (see scripts/__init__.py).
(fr) => {
  const rect = fr.getBoundingClientRect();
  const style = getComputedStyle(fr);
  const px = (v) => parseFloat(v) || 0;
  return [rect.left + px(style.borderLeftWidth) + px(style.paddingLeft),
          rect.top + px(style.borderTopWidth) + px(style.paddingTop)];
}
