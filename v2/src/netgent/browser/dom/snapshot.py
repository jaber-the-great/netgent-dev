"""DOM observation: snapshot a page's interactive elements into a structured tree.

Compile-time observation only. These objects are NOT part of the workflow artifact —
they feed the (LLM) Discovery/Generator so it can choose elements and emit durable
locator chains. At run time nothing here is used; the executor drives resolved locators.

The walker pierces shadow DOM and same-origin iframes (the stress-tests corpus is built
to break naive walkers: nested iframes, shadow-DOM forms, contenteditable, web components).
Each element carries an ordered candidate-selector list (role/test-id/label/css) so the
Generator can store the most durable one first.
"""

from pydantic import BaseModel, Field

# Injected into the page; returns a flat list of interactive-element descriptors.
# Kept dependency-free and defensive (wrapped in try/catch per node) so one weird node
# can't abort the whole snapshot.
DOM_SNAPSHOT_JS = r"""
() => {
  const INTERACTIVE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA']);
  const isInteractive = (el) => {
    if (INTERACTIVE.has(el.tagName)) return true;
    if (el.hasAttribute('role')) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.isContentEditable) return true;
    const ti = el.getAttribute && el.getAttribute('tabindex');
    return ti !== null && ti !== '-1';
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const accName = (el) => clean(
    el.getAttribute('aria-label') ||
    (el.labels && el.labels.length ? el.labels[0].childNodes[0]?.textContent : '') ||
    el.getAttribute('placeholder') ||
    el.getAttribute('name') ||
    (el.tagName === 'SELECT' ? '' : el.innerText) ||
    el.getAttribute('value') || ''
  );
  const cssPath = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let sel = node.tagName.toLowerCase();
      if (node.classList && node.classList.length) sel += '.' + [...node.classList].map(c => CSS.escape(c)).join('.');
      const parent = node.parentNode;
      if (parent) {
        const sibs = [...parent.children].filter(c => c.tagName === node.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(node) + 1})`;
      }
      parts.unshift(sel);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const ROLE_FOR_TAG = {A:'link', BUTTON:'button', INPUT:'textbox', SELECT:'combobox', TEXTAREA:'textbox'};
  const candidates = (el) => {
    const out = [];
    const role = el.getAttribute('role') || ROLE_FOR_TAG[el.tagName];
    const name = accName(el);
    if (role && name) out.push({ kind: 'role', role, name });
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test-id');
    if (tid) out.push({ kind: 'test_id', value: tid });
    if (name && el.labels && el.labels.length) out.push({ kind: 'label', value: name });
    out.push({ kind: 'css', value: cssPath(el) });
    return out;
  };

  const results = [];
  const walk = (root, framePath) => {
    let nodes;
    try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of nodes) {
      try {
        if (el.shadowRoot) walk(el.shadowRoot, framePath);
        if (!isInteractive(el) || !visible(el)) continue;
        const r = el.getBoundingClientRect();
        results.push({
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role') || null,
          name: accName(el),
          type: el.getAttribute('type') || null,
          value: (el.value !== undefined ? String(el.value).slice(0, 200) : null),
          framePath,
          bbox: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
          candidates: candidates(el),
        });
      } catch (e) { /* skip pathological node */ }
    }
  };
  walk(document, []);
  return results;
}
"""


class SelectorCandidate(BaseModel):
    kind: str  # role | test_id | label | css
    role: str | None = None
    name: str | None = None
    value: str | None = None


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class DomElement(BaseModel):
    tag: str
    role: str | None = None
    name: str = ""
    type: str | None = None
    value: str | None = None
    frame_path: list[str] = Field(default_factory=list, alias="framePath")
    bbox: BBox
    candidates: list[SelectorCandidate] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class DomSnapshot(BaseModel):
    url: str
    title: str
    elements: list[DomElement] = Field(default_factory=list)

    def interactive(self) -> list[DomElement]:
        return self.elements
