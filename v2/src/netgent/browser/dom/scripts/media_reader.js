// Playback ground truth for every media element handed in (`handles`: HTMLMediaElement JS
// handles resolved into THIS isolated world by browser/dom/media.py — attached or not) plus
// every <video>/<audio> attached to this frame's document, open shadow roots included. The
// two sets overlap and are deduped by identity: the heap query misses attached elements the
// page's script never touched (no JS wrapper exists for them), the DOM query misses detached
// ones (`new Audio()` players are never inserted — SoundCloud), so both are needed.
//
// Read-only property access on the isolated world's own wrappers — never call play()/pause(),
// and a page-side getter trap on the main world's HTMLMediaElement.prototype does not fire
// (tests/integration/test_media_detached.py). Properties, not accessibility strings: a
// player's on-screen controls freeze while auto-hidden; currentTime/paused cannot.
//
// Inclusion: a visible element always; an invisible or detached one only once it has started
// (playing now, or has ever played — `played` ranges / a position past 0) — a preloaded
// sound-effect pool or a spare `new Audio()` with nothing loaded is not a player the agent can
// act on. Load state travels with
// the reading: readyState 0 with no source (Twitch's `<video src="">` when the stream never
// attaches) renders as NOT LOADED instead of an ordinary pause the agent would toggle forever.
//
// Bare function expression after the leading `//` lines (see scripts/__init__.py).
(...handles) => {
  const seen = new Set();
  const els = [];
  const add = (el) => {
    if (el && el.nodeType === 1 && !seen.has(el)) { seen.add(el); els.push(el); }
  };
  const collect = (root) => {
    let found;
    try { found = root.querySelectorAll('video, audio'); } catch (e) { return; }
    for (const el of found) add(el);
    let all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of all) if (el.shadowRoot) collect(el.shadowRoot);
  };
  collect(document);
  for (const h of handles) add(h);
  const out = [];
  for (const v of els) {
    try {
      const attached = !!v.isConnected;
      const r = attached ? v.getBoundingClientRect() : null;
      const visible = !!r && (r.width > 0 || r.height > 0);
      const started = (v.currentTime || 0) > 0 || (v.played && v.played.length > 0);
      if (!visible && v.paused && !started) continue;
      const current = Math.floor(v.currentTime || 0);
      out.push({
        tag: v.tagName.toLowerCase(),
        current,
        duration: Number.isFinite(v.duration) ? Math.floor(v.duration) : null,
        paused: !!v.paused,
        ended: !!v.ended,
        muted: !!v.muted,
        attached,
        ready_state: v.readyState,
        network_state: v.networkState,
        has_source: !!(v.currentSrc || v.getAttribute('src') || v.srcObject || v.querySelector('source[src]')),
      });
    } catch (e) { /* skip pathological media node */ }
  }
  return out;
}
