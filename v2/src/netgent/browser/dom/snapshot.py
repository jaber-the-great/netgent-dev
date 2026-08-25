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
  // Roles you actually operate on. Container roles (radiogroup, group, list, tablist, …)
  // are NOT here: listing them makes the agent try to click a wrapper and time out.
  const INTERACTIVE_ROLES = new Set(['button','link','checkbox','radio','textbox','combobox',
    'searchbox','spinbutton','slider','switch','option','tab','menuitem','menuitemcheckbox',
    'menuitemradio','listbox']);
  const isInteractive = (el) => {
    if (INTERACTIVE.has(el.tagName)) return true;
    const role = el.getAttribute('role');
    if (role && INTERACTIVE_ROLES.has(role)) return true;
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
  const INPUT_ROLE = {checkbox:'checkbox', radio:'radio', button:'button', submit:'button', reset:'button',
                      range:'slider', search:'searchbox', email:'textbox', tel:'textbox', url:'textbox',
                      number:'spinbutton'};
  const TAG_ROLE = {A:'link', BUTTON:'button', SELECT:'combobox', TEXTAREA:'textbox'};
  const roleOf = (el) => el.getAttribute('role') ||
    (el.tagName === 'INPUT' ? (INPUT_ROLE[(el.getAttribute('type') || 'text').toLowerCase()] || 'textbox')
                            : TAG_ROLE[el.tagName]);
  const candidates = (el) => {
    const out = [];
    const role = roleOf(el);
    const name = accName(el);
    if (role && name) out.push({ kind: 'role', role, name });
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test-id');
    if (tid) out.push({ kind: 'test_id', value: tid });
    if (name && el.labels && el.labels.length) out.push({ kind: 'label', value: name });
    out.push({ kind: 'css', value: cssPath(el) });
    return out;
  };

  const results = [];
  const texts = [];
  const seenText = new Set();
  const directText = (el) => {
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    return clean(t);
  };
  const walk = (root) => {
    let nodes;
    try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of nodes) {
      try {
        if (el.shadowRoot) walk(el.shadowRoot);
        // iframes are NOT descended here — the Python layer iterates page.frames and
        // evaluates this walk inside EACH frame's own context (works cross-origin via CDP).
        if (el.tagName === 'IFRAME') continue;
        if (isInteractive(el)) {
          if (!visible(el)) continue;
          const r = el.getBoundingClientRect();
          results.push({
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || null,
            name: accName(el),
            type: el.getAttribute('type') || null,
            checked: (el.type === 'checkbox' || el.type === 'radio') ? !!el.checked : null,
            disabled: !!el.disabled,
            required: !!el.required,
            // A required field the browser considers invalid blocks native form submit
            // silently (the validation tooltip is not in the DOM) — surface it.
            invalid: el.willValidate ? !el.validity.valid : false,
            options: el.tagName === 'SELECT'
              ? [...el.options].map(o => o.value).filter(v => v).slice(0, 25) : null,
            value: (el.value !== undefined ? String(el.value).slice(0, 200) : null),
            framePath: [],  // set by the Python layer from Playwright's frame tree
            bbox: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
            candidates: candidates(el),
          });
        } else if (visible(el)) {
          // Salient visible text (headings, messages, labels) so the agent can read
          // confirmations and status — not just interactive elements.
          const t = directText(el);
          if (t && t.length > 1 && !seenText.has(t)) {
            const alert = el.getAttribute('role') === 'alert' || el.getAttribute('role') === 'status';
            seenText.add(t);
            texts.push({ text: t.slice(0, 200), alert });
          }
        }
      } catch (e) { /* skip pathological node */ }
    }
  };
  walk(document);
  return { elements: results, texts };
}
"""

# Computes a document-unique CSS selector for a given element (an <iframe>), evaluated in
# the element's OWN frame — used to build the frame_locator path for each Playwright frame.
FRAME_SELECTOR_JS = r"""
(fr) => {
  if (fr.id) return `iframe#${CSS.escape(fr.id)}`;
  if (fr.name) return `iframe[name="${CSS.escape(fr.name)}"]`;
  const parts = [];
  let node = fr;
  while (node && node.nodeType === 1 && parts.length < 6) {
    let sel = node.tagName.toLowerCase();
    if (node.id) { parts.unshift(`#${CSS.escape(node.id)}`); break; }
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
}
"""

# The top-left corner of an <iframe>'s CONTENT box in its parent's viewport: border-box
# left/top plus border and padding — the origin of the child document's coordinates.
# Puppeteer's #getTopLeftCornerOfFrame (puppeteer-core api/ElementHandle.ts:1380-1415).
FRAME_CONTENT_ORIGIN_JS = r"""
(fr) => {
  const rect = fr.getBoundingClientRect();
  const style = getComputedStyle(fr);
  const px = (v) => parseFloat(v) || 0;
  return [rect.left + px(style.borderLeftWidth) + px(style.paddingLeft),
          rect.top + px(style.borderTopWidth) + px(style.paddingTop)];
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
    checked: bool | None = None  # checkbox/radio state
    disabled: bool = False
    required: bool = False
    invalid: bool = False  # required-but-invalid: silently blocks native form submit
    options: list[str] | None = None  # <select> option values
    value: str | None = None
    frame_path: list[str] = Field(default_factory=list, alias="framePath")
    bbox: BBox
    candidates: list[SelectorCandidate] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class TextBlock(BaseModel):
    text: str
    alert: bool = False  # role=alert/status — a confirmation/error message
    frame_path: list[str] = Field(default_factory=list)  # which frame the text is in


class DomSnapshot(BaseModel):
    url: str
    title: str
    elements: list[DomElement] = Field(default_factory=list)
    texts: list[TextBlock] = Field(default_factory=list)
    viewport_height: int = 0  # top-frame innerHeight; 0 = unknown (show everything)
    # Frames whose walk failed (detached mid-snapshot, unreachable): their elements are
    # missing from this observation. Counted and named so the agent and the trajectory can
    # see the observation shrank, instead of it silently looking complete (browser-use #4778).
    frames_skipped: int = 0
    skipped_frames: list[str] = Field(default_factory=list)  # "<url>: <error>" per skipped frame

    def interactive(self) -> list[DomElement]:
        return self.elements

    def scoped_to(self, frame_path: list[str]) -> "DomSnapshot":
        """A copy restricted to one frame — its elements + texts only. Used to focus the
        agent on a single form (iframe) so a sweep can complete forms one at a time.

        viewport_height is zeroed so the observation is NOT paged: a single bounded form
        should be shown whole, otherwise fields page out of view and the agent scroll-
        thrashes looking for inputs it already filled."""
        return DomSnapshot(
            url=self.url,
            title=self.title,
            elements=[e for e in self.elements if e.frame_path == frame_path],
            texts=[t for t in self.texts if t.frame_path == frame_path],
            viewport_height=0,
            frames_skipped=self.frames_skipped,
            skipped_frames=self.skipped_frames,
        )
