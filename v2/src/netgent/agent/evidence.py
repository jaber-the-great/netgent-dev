"""Page evidence: what the page looked like after each exploration step.

Discovery records cheap, deterministic observations on every trajectory step — the URL,
title, a bounded sample of salient visible text, whether a <video> is present and
actually advancing, and the visibility of a few durable locators (the next step's
target). Synthesis compares this evidence ACROSS runs to derive state conditions that
are stronger than "the URL matched": a watch state is recognized by its player running,
a form state by its field being visible.

Lives in agent/: the schema and executor never depend on it.
"""

from pydantic import BaseModel, Field

from netgent.browser.session import BrowserSession
from netgent.schema.actions import Locator

MAX_TEXTS = 40
MAX_TEXT_LEN = 120

# Salient visible text: headings, buttons, links, labels, status/alert regions — bounded.
# Deterministic: document order, de-duplicated, capped in count and length.
EVIDENCE_JS = r"""
(limits) => {
  const [maxTexts, maxLen] = limits;
  const out = [];
  const seen = new Set();
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const sel = 'h1,h2,h3,h4,[role=heading],button,a,label,[role=alert],[role=status],[role=dialog] p,p';
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= maxTexts) break;
    try {
      if (!visible(el)) continue;
      const t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 3 || t.length > maxLen || seen.has(t)) continue;
      seen.add(t);
      out.push(t);
    } catch (e) { /* skip */ }
  }
  return { title: document.title || '', texts: out, videoPresent: !!document.querySelector('video') };
}
"""


class ElementProbe(BaseModel):
    """Visibility of one durable locator at capture time."""

    locator: Locator
    visible: bool


class PageEvidence(BaseModel):
    url: str
    title: str = ""
    texts: list[str] = Field(default_factory=list)  # bounded sample of salient visible text
    video_present: bool = False
    video_playing: bool = False  # currentTime advanced between two samples
    probes: list[ElementProbe] = Field(default_factory=list)


async def capture_evidence(
    session: BrowserSession, probes: list[Locator] | None = None, video_sample_ms: int = 250
) -> PageEvidence:
    """Observe the page once. Never raises — a page mid-navigation yields sparse evidence."""
    url = session.page.url
    try:
        raw = await session.page.evaluate(EVIDENCE_JS, [MAX_TEXTS, MAX_TEXT_LEN])
    except Exception:  # noqa: BLE001 — evidence is best-effort
        raw = {"title": "", "texts": [], "videoPresent": False}
    playing = await session.video_playing(sample_ms=video_sample_ms) if raw.get("videoPresent") else False
    checks = [ElementProbe(locator=chain, visible=await session.is_visible(chain)) for chain in (probes or [])]
    return PageEvidence(
        url=url,
        title=raw.get("title", ""),
        texts=list(raw.get("texts", [])),
        video_present=bool(raw.get("videoPresent")),
        video_playing=playing,
        probes=checks,
    )


def locator_of(action: object) -> Locator | None:
    """The locator chain an action targets, if it has one."""
    chain = getattr(action, "locator", None)
    return chain if chain else None
