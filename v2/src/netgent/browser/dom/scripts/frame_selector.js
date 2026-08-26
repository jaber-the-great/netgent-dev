// Computes a CSS selector for a frame-owner element (<iframe> or legacy <frame>), evaluated
// in the element's OWN frame — used to build the frame_locator path for each Playwright frame.
// The selector must be unique within the element's root (document or shadow root):
// frame_locator is strict (measured: `frame_locator("iframe")` with two matches is a strict-
// mode violation; `>> nth=N` disambiguates). Attribute preference follows Playwright's own
// iframe generator (injected/selectorGenerator.ts:222-236: test-id > name/title > #id), with
// values quoted as attribute selectors (quoteCSSAttributeValue) rather than CSS.escape'd —
// CSS.escape is for identifiers, not quoted strings (research doc "Where NetGent stands" #6).
//
// Bare function expression after the leading `//` lines (see scripts/__init__.py).
(fr) => {
  const tag = fr.tagName.toLowerCase();                       // iframe OR frame (framesets)
  const root = fr.getRootNode();
  const q = (v) => '"' + String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const matches = (sel) => { try { return [...root.querySelectorAll(sel)]; } catch (e) { return []; } };
  const unique = (sel) => { const m = matches(sel); return m.length === 1 && m[0] === fr; };
  const disambiguate = (sel) => {
    const m = matches(sel);
    const i = m.indexOf(fr);
    return i < 0 ? null : (m.length === 1 ? sel : `${sel} >> nth=${i}`);
  };
  const attrs = [['data-testid', 'data-testid'], ['name', 'name'], ['title', 'title']];
  for (const [attr] of attrs) {
    const v = fr.getAttribute(attr);
    if (v && unique(`${tag}[${attr}=${q(v)}]`)) return `${tag}[${attr}=${q(v)}]`;
  }
  if (fr.id && unique(`${tag}#${CSS.escape(fr.id)}`)) return `${tag}#${CSS.escape(fr.id)}`;
  // Generic ancestor path (stops at an #id or the root / shadow boundary), then verify it.
  const parts = [];
  let node = fr;
  while (node && node.nodeType === 1 && parts.length < 6) {
    let sel = node.tagName.toLowerCase();
    if (node.id && !/\d{4,}/.test(node.id)) { parts.unshift(`#${CSS.escape(node.id)}`); break; }
    if (node.classList && node.classList.length) sel += '.' + [...node.classList].map(c => CSS.escape(c)).join('.');
    const parent = node.parentNode;
    if (parent) {
      const sibs = [...parent.children].filter(c => c.tagName === node.tagName);
      if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(node) + 1})`;
    }
    parts.unshift(sel);
    node = node.parentElement;
  }
  const path = parts.join(' > ');
  if (unique(path)) return path;
  return disambiguate(path) || disambiguate(tag) || tag;
}
