// The DOM walker. Runs in an ISOLATED world (Playwright's default `frame.evaluate`, or the world
// `browser/dom/closed_shadow.py` creates over CDP) — never in the page's main world — and returns a
// flat list of interactive-element descriptors. It is read-only: nothing on the page is patched,
// defined, or stamped, so page JavaScript cannot tell it ran (a prototype lie such as a wrapped
// `attachShadow` is exactly the fingerprint docs/research/stealth-after-patchright.md forbids).
//
// Closed shadow roots are invisible to `el.shadowRoot`, so they are handed IN: `closedRoots`
// are ShadowRoot handles resolved from outside the page (CDP `DOM.describeNode(pierce)` →
// `DOM.resolveNode`, the same pierce Patchright's actions use). `root.host` maps each back to
// its host, so the walker descends at the host's position and element order is unchanged.
// Playwright's own `evaluate` passes one `undefined` argument — filtered out below.
// Kept dependency-free and defensive (wrapped in try/catch per node) so one weird node
// can't abort the whole snapshot.
//
// This file must stay a bare function expression after the leading `//` lines: the loader
// (scripts/__init__.py) strips them and hands the rest to `frame.evaluate` and to CDP
// `Runtime.callFunctionOn(functionDeclaration=…)` unchanged.
(...closedRoots) => {
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
    // Only the ROOT of a contenteditable region: its children (<p>, <br>, spans) are all
    // isContentEditable too and listing them buries the one actionable editor in noise.
    if (el.isContentEditable) return !(el.parentElement && el.parentElement.isContentEditable);
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
    // Rich-text editors (Quill: ql-editor, and aria-placeholder per ARIA 1.2) carry their
    // field name here — without it a contenteditable email field is an anonymous <div>
    // the model cannot find (measured: browser-use Rich Text form, agent scroll-thrashed).
    el.getAttribute('data-placeholder') ||
    el.getAttribute('aria-placeholder') ||
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
  const closedByHost = new Map();
  for (const root of closedRoots) {
    try { if (root && root.host) closedByHost.set(root.host, root); } catch (e) { /* not a root */ }
  }
  const walk = (root, inClosed) => {
    let nodes;
    try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of nodes) {
      try {
        if (el.shadowRoot) {
          walk(el.shadowRoot, inClosed);  // open root: pierced by Playwright anyway (no marker)
        } else {
          // A closed root is invisible to el.shadowRoot; CDP handed it in (Patchright only —
          // it is the engine that can act inside). Elements inside carry requiresClosedShadow
          // so a plain-Playwright replayer can refuse, and the synthesizer flags the action.
          const closed = closedByHost.get(el);
          if (closed) walk(closed, true);
        }
        // iframes are NOT descended here — the Python layer iterates page.frames and
        // evaluates this walk inside EACH frame's own context (works cross-origin via CDP).
        if (el.tagName === 'IFRAME') continue;
        if (isInteractive(el)) {
          // A hidden file input is still ACTIONABLE: set_input_files works on it, and custom
          // upload widgets (Bootstrap custom-file opacity:0, Material UI display:none behind a
          // styled label) hide the real input on purpose — measured on browser-use's stress
          // forms, where dropping them left the agent nothing valid to upload to.
          const hiddenFileInput = el.tagName === 'INPUT'
            && (el.getAttribute('type') || '').toLowerCase() === 'file' && !visible(el);
          if (!visible(el) && !hiddenFileInput) continue;
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
            requiresClosedShadow: !!inClosed,
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
  walk(document, false);
  return { elements: results, texts };
}
