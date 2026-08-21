"""Accessibility-tree observation backend (hybrid AX + DOM).

The second observation backend for the compile-time agent (`NETGENT_OBSERVATION=ax`). It
produces the SAME `DomSnapshot`/`DomElement` models as the DOM walk (`snapshot.py`) so the
LLM-facing observation, `to_action`, and the compiler are unchanged — only WHERE roles,
names, and the element set come from differs:

* **Tree, roles, names, refs:** Playwright's aria snapshot in AI mode
  (`page.locator("body").aria_snapshot(mode="ai", boxes=True)`). This is the engine behind
  `browser_snapshot` in microsoft/playwright-mcp: one call returns every frame (same- AND
  cross-origin, stitched server-side with `f<seq>e<n>` refs), pierces open shadow roots,
  computes accessible names with the very `accname` implementation `get_by_role(name=…)`
  matches against, and gives each visible, pointer-receiving node a `[ref=…]` that
  resolves back to the element through the `aria-ref=` selector engine.
* **DOM facts the AX tree doesn't carry:** per element, a single `locator("aria-ref=…")
  .evaluate(ELEMENT_FACTS_JS)` fetches tag/type (date, file, range…), required/invalid
  (native validation), `<select>` options, current value, stable ids/test-ids, a CSS path
  fallback, and the iframe chain selector. Calls are gathered concurrently; measured at
  ~0.3s for 200 elements — the same as the DOM walk.
* **DOM-structural interactives the AX tree cannot see:** `tabindex`/`onclick`/
  `contenteditable` boxes, `<summary>`, and scrollable containers come from the DOM walk
  in `extrasOnly` mode and are merged in (deduplicated by frame + bounding box). This is
  the hybrid browser-use/Stagehand converge on: AX for semantics, DOM for structure.

Prior art studied (see docs/research/accessibility-tree-observation.md): playwright-mcp
(aria-ref), vercel-labs/agent-browser (CDP getFullAXTree + role/name/nth fallback),
browserbase/stagehand (CDP AX + DOM → xpath), browser-use (CDP DOM + AX + DOMSnapshot).
"""

import re
from dataclasses import dataclass, field

import yaml

from netgent.browser.dom.snapshot import BBox, DomElement, SelectorCandidate, TextBlock

# Roles the agent operates on. Mirrors INTERACTIVE_ROLES in the DOM walk; `option` is
# excluded because options live inside a combobox's value dump, not on the page.
INTERACTIVE_ROLES = frozenset(
    {
        "button", "link", "checkbox", "radio", "textbox", "combobox", "searchbox", "spinbutton",
        "slider", "switch", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "listbox",
        "treeitem", "option",
    }
)
# Roles whose text is a message to the reader (not a control); `alert`/`status` are
# surfaced as !ALERT lines like the DOM walk does for role=alert/status.
ALERT_ROLES = frozenset({"alert", "status"})
# Roles that never contribute text (their name is the control's label, shown on the element).
_NO_TEXT_ROLES = INTERACTIVE_ROLES | {"iframe", "img", "separator"}
_NAMED_CONTAINER_ROLES = frozenset({"group", "region", "dialog", "alertdialog", "form", "navigation", "tabpanel"})
_CHECKABLE_ROLES = frozenset({"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"})

# Builds the same candidate facts the DOM walk computes, for ONE element (resolved via
# aria-ref). Self-contained and defensive: a pathological element yields partial facts.
ELEMENT_FACTS_JS = r"""
(el) => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const cssPath = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let sel = node.tagName.toLowerCase();
      // anchor at the nearest ancestor with a stable-looking id: shorter, survives layout churn
      if (node !== el && node.id && !/\d{4,}|[0-9a-f]{8,}/.test(node.id)) {
        parts.unshift(`#${CSS.escape(node.id)}`); break;
      }
      if (node.classList && node.classList.length) sel += '.' + [...node.classList].map(c => CSS.escape(c)).join('.');
      const parent = node.parentNode;
      if (parent && parent.children) {
        const sibs = [...parent.children].filter(c => c.tagName === node.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(node) + 1})`;
      }
      parts.unshift(sel);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const tag = el.tagName.toLowerCase();
  const type = el.getAttribute('type');
  const out = { tag, type: type ? type.toLowerCase() : null, css: cssPath(el) };
  try {
    out.checked = (el.type === 'checkbox' || el.type === 'radio') ? !!el.checked : null;
    out.disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
    out.required = !!el.required || el.getAttribute('aria-required') === 'true';
    out.invalid = el.willValidate ? !el.validity.valid : false;
    out.options = tag === 'select' ? [...el.options].map(o => o.value).filter(v => v).slice(0, 25) : null;
    out.value = el.value !== undefined && tag !== 'button' ? String(el.value).slice(0, 200) : null;
    out.testId = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || null;
    out.hasLabel = !!(el.labels && el.labels.length);
    out.editable = !!el.isContentEditable;
    // Display-only fallback when the accessible name is empty (icon links, thumbnails):
    // what a sighted user reads. Never used for the role locator.
    out.fallbackName = clean(el.getAttribute('title') || el.getAttribute('placeholder') ||
      el.getAttribute('alt') || (el.labels && el.labels[0] ? el.labels[0].textContent : '') ||
      (tag === 'select' ? '' : el.innerText) || '').slice(0, 120);
    if (tag === 'details' || tag === 'summary') out.expanded = !!(el.closest('details') || {}).open;
  } catch (e) { /* partial facts are fine */ }
  return out;
}
"""

_HEAD_RE = re.compile(r'^([a-zA-Z]+)(?: "((?:[^"\\]|\\.)*)")?((?:\s*\[[^\]]*\])*)\s*$')
_ATTR_RE = re.compile(r"\[([a-zA-Z-]+)(?:=([^\]]*))?\]")


@dataclass
class AxNode:
    """One node of the parsed aria snapshot."""

    role: str
    name: str = ""
    attrs: dict[str, str | bool] = field(default_factory=dict)
    text: str | None = None  # inline value/text after the colon (e.g. a textbox value)
    children: list["AxNode"] = field(default_factory=list)

    @property
    def ref(self) -> str | None:
        r = self.attrs.get("ref")
        return r if isinstance(r, str) else None

    @property
    def box(self) -> BBox | None:
        b = self.attrs.get("box")
        if not isinstance(b, str):
            return None
        try:
            x, y, w, h = (int(float(v)) for v in b.split(","))
        except ValueError:
            return None
        return BBox(x=x, y=y, w=w, h=h)


def _parse_head(head: str) -> AxNode | None:
    m = _HEAD_RE.match(head.strip())
    if not m:
        return None
    role, name, attr_blob = m.group(1), m.group(2) or "", m.group(3) or ""
    attrs: dict[str, str | bool] = {}
    for k, v in _ATTR_RE.findall(attr_blob):
        attrs[k] = v if v != "" else True
    return AxNode(role=role, name=name.replace('\\"', '"'), attrs=attrs)


def _parse_items(items: object) -> list[AxNode]:
    """Convert the YAML list the aria snapshot renders into AxNodes."""
    nodes: list[AxNode] = []
    if not isinstance(items, list):
        return nodes
    for item in items:
        if isinstance(item, str):
            node = _parse_head(item)
            if node is None:  # a bare string child = text content
                node = AxNode(role="text", text=item)
            nodes.append(node)
        elif isinstance(item, dict):
            for key, value in item.items():
                key = str(key)
                if key == "text":
                    nodes.append(AxNode(role="text", text=str(value)))
                    continue
                if key.startswith("/"):  # /url, /placeholder … — node properties, not children
                    continue
                node = _parse_head(key)
                if node is None:
                    nodes.append(AxNode(role="text", text=f"{key}: {value}" if value is not None else key))
                    continue
                if isinstance(value, list):
                    node.children = _parse_items(value)
                elif value is not None:
                    node.text = str(value)
                nodes.append(node)
    return nodes


def parse_aria_snapshot(text: str) -> list[AxNode]:
    """Parse Playwright's aria snapshot YAML (any mode) into a tree of AxNodes."""
    if not text.strip():
        return []
    data = yaml.safe_load(text)
    return _parse_items(data)


@dataclass
class AxInteractive:
    """An interactive AX node with its frame chain (iframe refs) and top-viewport bbox."""

    node: AxNode
    frame_refs: list[str]  # refs of the enclosing iframe nodes, outermost first
    bbox: BBox


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _is_interactive(node: AxNode) -> bool:
    if node.role in INTERACTIVE_ROLES and node.role != "option":
        return True
    # A clickable generic/text box the author styled with cursor:pointer but gave no role —
    # the "div button". Only when it carries text to act on, like browser-use/agent-browser.
    return node.attrs.get("cursor") == "pointer" and bool(node.name or node.text) and not node.children


def collect(nodes: list[AxNode]) -> tuple[list[AxInteractive], list[tuple[list[str], TextBlock]], list[str]]:
    """Walk the tree: interactive nodes (with frame chain + offset bbox), merged text
    blocks as (iframe-ref chain, block) in document order, and the iframe refs seen."""
    interactives: list[AxInteractive] = []
    texts: list[tuple[list[str], TextBlock]] = []
    iframes: list[str] = []
    seen_text: set[str] = set()

    def leaf_text(n: AxNode) -> str | None:
        """Text a node contributes as a reader-facing fragment (None if it's a control)."""
        if n.role in _NO_TEXT_ROLES:
            return None
        if n.children:
            return None
        parts = [n.name, n.text] if n.role != "text" else [n.text]
        t = _clean(" ".join(p for p in parts if p))
        return t or None

    def push_text(frame_refs: list[str], t: str, alert: bool, y: int | None) -> None:
        t = t[:200]
        if len(t) > 1 and t not in seen_text:
            seen_text.add(t)
            texts.append((frame_refs, TextBlock(text=t, alert=alert, frame_path=[], y=y)))

    def y_of(n: AxNode, offset: tuple[int, int]) -> int | None:
        return n.box.y + offset[1] if n.box is not None else None

    def walk(n: AxNode, frame_refs: list[str], offset: tuple[int, int]) -> None:
        # A named landmark/group heads its content ("Rate your experience *").
        if n.name and n.role in _NAMED_CONTAINER_ROLES and n.children:
            push_text(frame_refs, n.name, n.role in ALERT_ROLES, y_of(n, offset))
        run: list[str] = []  # consecutive inline fragments → one block ("Score: 0 / 17")

        def flush() -> None:
            if run:
                push_text(frame_refs, " ".join(run), n.role in ALERT_ROLES, y_of(n, offset))
                run.clear()

        for c in n.children:
            box = c.box
            if _is_interactive(c):
                flush()
                if box is not None:
                    interactives.append(
                        AxInteractive(
                            node=c, frame_refs=list(frame_refs),
                            bbox=BBox(x=box.x + offset[0], y=box.y + offset[1], w=box.w, h=box.h),
                        )
                    )
                continue  # a combobox/listbox's options are its value list, not separate targets
            lt = leaf_text(c)
            if lt is not None:
                if c.role in ("text", "generic"):
                    run.append(lt)  # inline fragment
                else:  # a block of its own: paragraph, heading, alert, cell, listitem …
                    flush()
                    alert = c.role in ALERT_ROLES or n.role in ALERT_ROLES
                    push_text(frame_refs, lt, alert, y_of(c, offset) if box is not None else y_of(n, offset))
                continue
            flush()
            if c.role == "iframe":
                ref = c.ref
                if ref is None or box is None:
                    continue
                iframes.append(ref)
                walk(c, frame_refs + [ref], (offset[0] + box.x, offset[1] + box.y))
                continue
            walk(c, frame_refs, offset)
        flush()

    root = AxNode(role="document", children=nodes)
    walk(root, [], (0, 0))
    return interactives, texts, iframes


def build_elements(
    interactives: list[AxInteractive],
    facts: dict[str, dict | None],
    frame_selectors: dict[str, str],
) -> list[DomElement]:
    """Join AX nodes with their DOM facts into DomElements with durable candidates.

    Candidate order: role+name (exact — it IS Playwright's computed name; `.nth` added when
    the same frame has several identical role+name nodes) → test-id → label → css.
    """
    # duplicates of (frame chain, role, name) get an nth so the locator stays unique
    counts: dict[tuple[tuple[str, ...], str, str], int] = {}
    for it in interactives:
        key = (tuple(it.frame_refs), it.node.role, it.node.name)
        counts[key] = counts.get(key, 0) + 1
    seen_nth: dict[tuple[tuple[str, ...], str, str], int] = {}

    elements: list[DomElement] = []
    for it in interactives:
        n = it.node
        f = facts.get(n.ref or "") or {}
        key = (tuple(it.frame_refs), n.role, n.name)
        nth = None
        if counts[key] > 1:
            nth = seen_nth.get(key, 0)
            seen_nth[key] = nth + 1

        tag = f.get("tag") or ("div" if n.role == "generic" else n.role)
        role = n.role if n.role != "generic" else "button"
        checked = f.get("checked")
        if checked is None and n.role in _CHECKABLE_ROLES:
            checked = n.attrs.get("checked") is True
        value = f.get("value")
        if value is None and n.text and n.role not in ("link", "button"):
            value = n.text[:200]
        if n.role == "slider" and f.get("value") is None and n.text:
            value = n.text

        candidates: list[SelectorCandidate] = []
        if n.name and n.role != "generic":
            candidates.append(SelectorCandidate(kind="role", role=n.role, name=n.name, exact=True, nth=nth))
        if f.get("testId"):
            candidates.append(SelectorCandidate(kind="test_id", value=f["testId"]))
        if n.name and f.get("hasLabel"):
            candidates.append(SelectorCandidate(kind="label", value=n.name, exact=True, nth=nth))
        if f.get("css"):
            candidates.append(SelectorCandidate(kind="css", value=f["css"]))
        if not candidates and n.ref:
            # last resort — only valid for the current snapshot, never replayable
            candidates.append(SelectorCandidate(kind="css", value=f"aria-ref={n.ref}"))

        frame_path = [frame_selectors[r] for r in it.frame_refs if r in frame_selectors]
        if len(frame_path) != len(it.frame_refs):
            continue  # an iframe we could not resolve a selector for: skip its content
        elements.append(
            DomElement(
                tag=tag,
                role=role if role != tag else None,
                name=n.name or (f.get("fallbackName") or ""),
                type=f.get("type"),
                checked=checked,
                disabled=bool(f.get("disabled")) or n.attrs.get("disabled") is True,
                required=bool(f.get("required")),
                invalid=bool(f.get("invalid")) or n.attrs.get("invalid") is True,
                options=f.get("options"),
                value=value,
                frame_path=frame_path,
                bbox=it.bbox,
                candidates=candidates,
            )
        )
    return elements


def merge_extras(elements: list[DomElement], extras: list[DomElement]) -> list[DomElement]:
    """Add DOM-structural interactives the AX tree lacks, skipping any that coincide
    (same frame, same bounding box ±2px) with an element already listed."""
    def key(e: DomElement) -> tuple[tuple[str, ...], int, int, int, int]:
        return (tuple(e.frame_path), e.bbox.x // 3, e.bbox.y // 3, e.bbox.w // 3, e.bbox.h // 3)

    seen = {key(e) for e in elements}
    out = list(elements)
    for e in extras:
        if key(e) in seen:
            continue
        seen.add(key(e))
        # slot it in reading order (before the first listed element below it) so indices
        # follow the page top-to-bottom like the DOM walk's tree order
        pos = next((i for i, x in enumerate(out) if x.bbox.y > e.bbox.y), len(out))
        out.insert(pos, e)
    return out
