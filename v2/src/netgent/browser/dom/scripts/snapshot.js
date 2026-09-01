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
  // VIDEO/AUDIO are interactive on purpose: a visible player is a real click target (players
  // toggle play/pause on click) and the natural receiver for keyboard shortcuts (k/l/j,
  // arrows) — without it listed, an agent that must seek precisely has no element to press
  // on and falls back to proportional seek-bar clicks (measured: 4-minute overshoots on
  // YouTube). Invisible/0x0 media (background <audio>) is still filtered by visible().
  const INTERACTIVE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA','VIDEO','AUDIO']);
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
    // checkVisibility (native, Chromium) sees what the own-style check below cannot: an
    // ANCESTOR's opacity:0. YouTube auto-hides its control bar that way and stops updating
    // the hidden controls' labels — without the ancestor check the walker reports a frozen
    // "Play (k)" / timer as live UI (measured: the pause-toggle and frozen-ad stuck loops).
    if (el.checkVisibility) {
      try { return el.checkVisibility({ opacityProperty: true, visibilityProperty: true }); }
      catch (e) { /* fall through to the own-style check */ }
    }
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  // Zero-width characters count as content but carry none — MUI renders an empty select's
  // display as U+200B, which otherwise becomes a "name"/"value" of invisible text.
  const clean = (s) => (s || '').replace(/[\u200b\u200c\u200d\ufeff]/g, '')
    .replace(/\s+/g, ' ').trim().slice(0, 120);
  const labelledBy = (el) => {
    // ARIA name computation step 2B (aria-labelledby): MUI selects carry their whole name
    // here ("Country") while their text content is a zero-width space — measured.
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (!ids.length) return '';
    const root = el.getRootNode();
    return ids.map((id) => { const n = root.getElementById && root.getElementById(id);
      return n && n !== el ? n.textContent : ''; }).join(' ');
  };
  const accName = (el) => clean(
    el.getAttribute('aria-label') ||
    labelledBy(el) ||
    // A label's FIRST child node when it is real text ("Email <input>"), else the whole
    // label text — a wrapping label often starts with whitespace before the input, and
    // childNodes[0] alone then yields an empty name (measured: MUI PrivateSwitchBase).
    (el.labels && el.labels.length
      ? ((el.labels[0].childNodes[0]?.textContent || '').trim()
         ? el.labels[0].childNodes[0].textContent : el.labels[0].textContent)
      : '') ||
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
    // Structural path only: tag + nth-of-type. No class names — nth-of-type already makes
    // each hop unique among its siblings, and classes flip with STATE (measured: Quill drops
    // ql-blank on first input, so a class-bearing chain resolved to 0 right after the fill it
    // was captured for). An #id (when present and stable-looking) still short-circuits.
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let sel = node.tagName.toLowerCase();
      if (node.id && !/\d{4,}/.test(node.id)) { parts.unshift(`#${CSS.escape(node.id)}`); break; }
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
  // Date-format hint for INPUTs, from signals readable without page JS
  // (docs/research/browser-agent-date-inputs.md §5, §7a). Native date/time types take ISO;
  // a text input gets a format only when a signal actually carries one: an attribute that
  // states it (uib-datepicker-popup, data-date-format), a placeholder that looks like one,
  // or a known picker library whose documented default we can cite. Never guessed from the
  // label — a wrong format= is worse than none. bootstrap-datepicker's component mode leaves
  // nothing on the input itself: the wrapper `.input-group.date` is the only signal (measured
  // on browser-use's jquery-bootstrap stress form), hence the ancestor check.
  const ISO_FORMAT = { date: 'YYYY-MM-DD', time: 'HH:MM', 'datetime-local': 'YYYY-MM-DDTHH:MM',
                       month: 'YYYY-MM', week: 'YYYY-Www' };
  const PICKERS = [
    ['flatpickr', (el) => el.classList.contains('flatpickr-input'), 'YYYY-MM-DD'],
    ['jquery-ui-datepicker', (el) => el.classList.contains('hasDatepicker'), 'MM/DD/YYYY'],
    ['react-datepicker', (el) => !!el.closest('.react-datepicker__input-container'), 'MM/DD/YYYY'],
    ['ant-picker', (el) => !!el.closest('.ant-picker'), 'YYYY-MM-DD'],
    ['bootstrap-datepicker', (el) => el.getAttribute('data-provide') === 'datepicker'
        || /(^|\s)(datepicker|datetimepicker|daterangepicker)(\s|$)/i.test(el.className)
        || !!el.closest('.input-group.date'), 'MM/DD/YYYY'],
  ];
  const dateHint = (el) => {
    if (el.tagName !== 'INPUT') return { format: null, picker: null };
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (ISO_FORMAT[t]) return { format: ISO_FORMAT[t], picker: null };
    if (t !== 'text' && t !== '') return { format: null, picker: null };
    const explicit = el.getAttribute('uib-datepicker-popup')
      || el.getAttribute('data-date-format') || el.getAttribute('data-format');
    if (explicit) return { format: explicit.toUpperCase(), picker: 'attr' };
    for (const a of ['placeholder', 'title', 'aria-placeholder', 'data-placeholder']) {
      const v = (el.getAttribute(a) || '').trim();
      if (/^[dmy][dmy\W]{5,}$/i.test(v)) return { format: v.toUpperCase(), picker: null };
    }
    for (const [name, test, fmt] of PICKERS) {
      if (!test(el)) continue;
      const lang = (document.documentElement.lang || navigator.language || 'en-US').toLowerCase();
      const localeFmt = fmt === 'MM/DD/YYYY' && !lang.startsWith('en-us') && lang !== 'en' ? 'DD/MM/YYYY' : fmt;
      return { format: localeFmt, picker: name };
    }
    return { format: null, picker: null };
  };
  // Framework-side invalidity (Angular ng-invalid, Bootstrap is-invalid, aria-invalid): the
  // only machine-readable evidence that a page PARSED and rejected a value while native
  // validity stays true (measured: angularjs stress form, ISO date silently dropped).
  const frameworkInvalid = (el) =>
    el.classList.contains('ng-invalid') || el.classList.contains('is-invalid')
    || el.getAttribute('aria-invalid') === 'true';

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
  // Media ground truth, read from the element PROPERTIES — currentTime/paused never freeze,
  // unlike YouTube's accessibility strings, which stop updating while the control bar is
  // auto-hidden. Read-only property access; never call play()/pause() here. An invisible but
  // audibly playing element (background <audio>) is still reported.
  const media = [];
  const observeMedia = (el) => {
    try {
      if (!visible(el) && el.paused) return;
      media.push({
        tag: el.tagName.toLowerCase(),
        current: Math.floor(el.currentTime || 0),
        duration: Number.isFinite(el.duration) ? Math.floor(el.duration) : null,
        paused: !!el.paused,
        ended: !!el.ended,
        muted: !!el.muted,
      });
    } catch (e) { /* skip pathological media node */ }
  };
  const seenText = new Set();
  // Inline children are part of their parent's sentence: "Score: <span>1</span> / 17" must
  // read as one text block, not "Score: / 17" plus a stray "1" (measured on the challenge
  // page: the agent could not see the score change). Merged children are skipped later.
  const INLINE = new Set(['SPAN','B','I','EM','STRONG','SMALL','CODE','SUP','SUB','MARK','U','S','ABBR','TIME']);
  const merged = new Set();
  const directText = (el) => {
    let t = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) t += n.textContent;
      else if (n.nodeType === 1 && INLINE.has(n.tagName) && !n.shadowRoot && !isInteractive(n)) {
        t += ' ' + n.textContent + ' ';
        merged.add(n);
      }
    }
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
        if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') observeMedia(el);
        if (isInteractive(el)) {
          // A hidden file input is still ACTIONABLE: set_input_files works on it, and custom
          // upload widgets (Bootstrap custom-file opacity:0, Material UI display:none behind a
          // styled label) hide the real input on purpose — measured on browser-use's stress
          // forms, where dropping them left the agent nothing valid to upload to.
          const itype = el.tagName === 'INPUT' ? (el.getAttribute('type') || '').toLowerCase() : '';
          const hiddenProxyInput = !visible(el) && (
            itype === 'file'
            // Custom radio/checkbox widgets hide the real input and style its LABEL (MUI
            // PrivateSwitchBase, Rich-Text contact radios — measured): the input is still
            // the actionable element (our click ladder clicks the label), so observe it and
            // report the label's geometry.
            || ((itype === 'radio' || itype === 'checkbox') && el.labels && el.labels.length > 0)
          );
          if (!visible(el) && !hiddenProxyInput) continue;
          const rectSource = (hiddenProxyInput && el.labels && el.labels.length && itype !== 'file')
            ? el.labels[0] : el;
          const r = rectSource.getBoundingClientRect();
          results.push({
            tag: el.tagName.toLowerCase(),
            // Contenteditable's implicit ARIA role: shown as a fillable textbox, otherwise a
            // rich-text editor renders as a bare <div> the model only thinks to click.
            role: el.getAttribute('role') || (el.isContentEditable ? 'textbox' : null),
            name: accName(el),
            type: el.getAttribute('type') || null,
            // Native checked, or the ARIA toggle state (aria-pressed buttons, aria-checked
            // customs): without it a selected toggle looks identical to an unselected one
            // and the model re-clicks it forever (measured: React Native Web contact buttons).
            checked: (el.type === 'checkbox' || el.type === 'radio') ? !!el.checked
              : (el.hasAttribute('aria-pressed') ? el.getAttribute('aria-pressed') === 'true'
                : (el.hasAttribute('aria-checked') ? el.getAttribute('aria-checked') === 'true' : null)),
            disabled: !!el.disabled,
            required: !!el.required,
            // A required field the browser considers invalid blocks native form submit
            // silently (the validation tooltip is not in the DOM) — surface it.
            invalid: (el.willValidate ? !el.validity.valid : false) || frameworkInvalid(el),
            ...dateHint(el),
            options: el.tagName === 'SELECT'
              ? [...el.options].map(o => o.value).filter(v => v).slice(0, 25) : null,
            // Native value, or — for popup widgets (MUI/ARIA selects: div[role=button]
            // aria-haspopup, [role=combobox]) — the text they DISPLAY, which is their
            // selection. Without it a chosen option is invisible in the observation and the
            // model reopens the menu forever (measured: MUI Country dropdown).
            value: (el.value !== undefined ? String(el.value).slice(0, 200)
              : ((el.getAttribute('aria-haspopup') === 'listbox' || el.getAttribute('role') === 'combobox'
                  // ...and a contenteditable editor's text IS its value: without it the model
                  // cannot see that its fill landed and re-fills forever (measured: Quill form).
                  || el.isContentEditable)
                 ? (clean(el.textContent).slice(0, 60) || null) : null)),
            framePath: [],  // set by the Python layer from Playwright's frame tree
            requiresClosedShadow: !!inClosed,
            bbox: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
            candidates: candidates(el),
          });
        } else if (visible(el) && !merged.has(el)) {
          // Salient visible text (headings, messages, labels) so the agent can read
          // confirmations and status — not just interactive elements.
          const t = directText(el);
          // Single characters are kept only when they carry state (a score digit, a check
          // mark): "Score: <span>1</span>" is otherwise invisible, and a click that only
          // bumps it reads as a no-op (measured on the challenge page).
          if (t && (t.length > 1 || /^[0-9✓✔✗]$/.test(t)) && !seenText.has(t)) {
            const alert = el.getAttribute('role') === 'alert' || el.getAttribute('role') === 'status';
            seenText.add(t);
            texts.push({ text: t.slice(0, 200), alert });
          }
        }
      } catch (e) { /* skip pathological node */ }
    }
  };
  walk(document, false);
  return { elements: results, texts, media };
}
