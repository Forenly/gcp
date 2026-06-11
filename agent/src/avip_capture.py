"""Real screen capture for the /presentation pipeline (Step 1).

A background thread drives headless Chromium via Playwright, records the
scripted tour of the target URL, transcodes WebM→MP4 into VIDEO_DIR and
streams real progress lines that the frontend polls. The cursor-pointed
targets are persisted as a tour manifest — they become the narration
waypoints the avatar speaks to in the VLM analysis step.
"""
import json
import re
import subprocess
import tempfile
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from avip_common import VIDEO_DIR

router = APIRouter()

_capture_job = {"status": "idle", "file": None, "logs": []}

# Headless Chromium renders no OS cursor, so the recording would show none.
# Inject a fake cursor (SVG arrow) + a soft highlight ring that follow real
# mousemove events, plus a click-ripple pulse — the Trupeer/Screenity overlay
# pattern (absolutely positioned, pointer-events:none, max z-index).
_CURSOR_OVERLAY_JS = """
(() => {
  const init = () => {
    if (document.getElementById('__avip_cursor')) return;
    const ring = document.createElement('div');
    ring.id = '__avip_ring';
    ring.style.cssText = 'position:fixed;top:-100px;left:-100px;width:46px;height:46px;' +
      'border-radius:50%;background:rgba(229,106,74,.2);border:2px solid rgba(229,106,74,.85);' +
      'transform:translate(-50%,-50%);pointer-events:none;z-index:2147483646;' +
      'transition:top 0.12s cubic-bezier(0.25, 1, 0.5, 1), left 0.12s cubic-bezier(0.25, 1, 0.5, 1);';
    const cur = document.createElement('div');
    cur.id = '__avip_cursor';
    cur.style.cssText = 'position:fixed;top:0;left:0;width:22px;height:22px;' +
      'pointer-events:none;z-index:2147483647;transform:translate(-100px,-100px);' +
      'transition:none;';
    cur.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24">' +
      '<path d="M5 2l15 10-7 1.2-3.4 6.3z" fill="#1a1a1a" stroke="#fff" stroke-width="1.6"/></svg>';
    document.documentElement.appendChild(ring);
    document.documentElement.appendChild(cur);
    let lx = 100, ly = 100;

    const updatePos = (x, y) => {
      lx = x; ly = y;
      cur.style.transform = `translate(${x}px, ${y}px)`;
      ring.style.left = `${x}px`;
      ring.style.top = `${y}px`;
    };

    document.addEventListener('mousemove', e => {
      updatePos(e.clientX, e.clientY);
    }, { passive: true, capture: true });

    let activeAnim = null;

    window.__avipMoveCursor = (targetX, targetY) => {
      if (activeAnim) cancelAnimationFrame(activeAnim);

      const startX = lx;
      const startY = ly;
      const dx = targetX - startX;
      const dy = targetY - startY;
      const distance = Math.hypot(dx, dy);

      if (distance < 5) {
        updatePos(targetX, targetY);
        return;
      }

      const duration = Math.min(750, Math.max(350, distance * 0.75));
      const perpX = -dy;
      const perpY = dx;
      const len = Math.hypot(perpX, perpY);
      const curveFactor = 0.2 * (Math.sin(startX + startY) > 0 ? 1 : -1);
      const offset = distance * curveFactor;

      const cp1x = startX + dx * 0.3 + (perpX / len) * offset;
      const cp1y = startY + dy * 0.3 + (perpY / len) * offset;
      const cp2x = startX + dx * 0.7 + (perpX / len) * offset * 0.5;
      const cp2y = startY + dy * 0.7 + (perpY / len) * offset * 0.5;

      const startTime = performance.now();
      const easeInOutCubic = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

      const animate = (now) => {
        const elapsed = now - startTime;
        const progress = Math.min(1, elapsed / duration);
        const t = easeInOutCubic(progress);

        const mt = 1 - t;
        const mt2 = mt * mt;
        const mt3 = mt2 * mt;
        const t2 = t * t;
        const t3 = t2 * t;

        const x = mt3 * startX + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * targetX;
        const y = mt3 * startY + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * targetY;

        updatePos(x, y);

        if (progress < 1) {
          activeAnim = requestAnimationFrame(animate);
        } else {
          updatePos(targetX, targetY);
          activeAnim = null;
        }
      };
      activeAnim = requestAnimationFrame(animate);
    };

    window.__avipPulse = () => {
      const p = document.createElement('div');
      p.style.cssText = 'position:fixed;left:' + lx + 'px;top:' + ly + 'px;width:18px;height:18px;' +
        'border-radius:50%;border:3px solid rgba(229,106,74,.9);background:rgba(229,106,74,.35);' +
        'transform:translate(-50%,-50%) scale(1);pointer-events:none;z-index:2147483645;' +
        'transition:transform .6s cubic-bezier(.25,.8,.25,1),opacity .6s ease;';
      document.documentElement.appendChild(p);
      requestAnimationFrame(() => {
        p.style.transform = 'translate(-50%,-50%) scale(3.4)';
        p.style.opacity = '0';
      });
      setTimeout(() => p.remove(), 700);
    };
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


class CaptureRequest(BaseModel):
    url: str
    file: str


def _cap_log(msg: str):
    _capture_job["logs"].append(msg)
    print(f"[capture] {msg}")


def _demo_advisor_form(page, rec_t0, tour_waypoints):
    """Interactive tour segment: fill the 'Try the advisor' form on camera —
    cursor-click each field, type sample yard specs, trigger a REAL /recommend
    (Gemini + MongoDB) and showcase the generated deployment plan. Waypoints
    are appended so the avatar narrates the interaction."""

    def locate(selector):
        # Scroll the element to center first, then re-read its rect once the
        # smooth scroll has settled — otherwise coords describe the old position.
        found = page.evaluate(
            "(sel) => { const el = document.querySelector(sel); if (!el) return false;"
            " el.scrollIntoView({ behavior: 'smooth', block: 'center' }); return true; }",
            selector)
        if not found:
            return None
        page.wait_for_timeout(800)
        return page.evaluate(
            "(sel) => { const el = document.querySelector(sel); if (!el) return null;"
            " const r = el.getBoundingClientRect();"
            " return { x: Math.round(r.left + Math.min(r.width / 2, 160)), y: Math.round(r.top + r.height / 2) }; }",
            selector)

    def point(selector, dwell_ms=700):
        coords = locate(selector)
        if not coords:
            return None
        page.mouse.move(coords["x"], coords["y"])
        page.evaluate(f"window.__avipMoveCursor && window.__avipMoveCursor({coords['x']}, {coords['y']})")
        page.wait_for_timeout(dwell_ms)
        return coords

    def click_pulse(selector):
        coords = point(selector)
        if not coords:
            return None
        page.evaluate("window.__avipPulse && window.__avipPulse()")
        page.click(selector)
        return coords

    def type_into(selector, value):
        if click_pulse(selector) is None:
            return
        page.keyboard.press("Control+A")
        page.keyboard.type(value, delay=70)
        page.wait_for_timeout(400)

    def waypoint(name, text, context, coords):
        tour_waypoints.append({
            "t": round(time.monotonic() - rec_t0, 1),
            "name": name, "tag": "form", "text": text, "context": context,
            "x": (coords or {}).get("x", 0), "y": (coords or {}).get("y", 0),
        })

    try:
        _cap_log("[Agent] Interactive demo: filling the advisor form with sample yard specs...")
        coords = point("#try h2", dwell_ms=1200)
        waypoint("Try the advisor — live demo", "Try the advisor",
                 "The agent fills the yard form on camera and generates a real deployment plan.", coords)

        # Sample yard: address + specs typed visibly, dropdowns picked with a pulse.
        type_into("#addr", "Hyde Park, London")
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        type_into("#area", "850")
        type_into("#slope", "18")
        type_into("#obstacles", "pond, trees")
        for sel, val in (("#boundary", "open"), ("#charging", "shed-power"), ("#terrain", "sloped")):
            if point(sel, dwell_ms=500):
                page.evaluate("window.__avipPulse && window.__avipPulse()")
                try:
                    page.select_option(sel, val)
                except Exception:
                    pass
                page.wait_for_timeout(500)

        _cap_log("[Agent] Clicking 'Generate Deployment Plan' — live Gemini + MongoDB reasoning run...")
        coords = click_pulse("#run")
        waypoint("Generate Deployment Plan", "Generate Deployment Plan",
                 "Gemini reasons over the MongoDB registry live; the on-page stepper shows each MCP tool call.", coords)

        # The real Gemini tool loop takes ~25-60s; the page's progress stepper
        # animates on camera while we hold here.
        page.wait_for_selector("#result .name", timeout=120000)
        _cap_log("[Agent] Deployment plan received — showcasing the recommendation...")

        coords = point("#result .name", dwell_ms=900)
        page.evaluate("window.__avipPulse && window.__avipPulse()")
        name_txt = (page.evaluate("(document.querySelector('#result .name')||{textContent:''}).textContent") or "").strip()
        waypoint("Recommended deployment", name_txt or "Recommendation",
                 "Generated live: recommended mower, dock, boundary, schedule and a Day 1-4 rollout.", coords)
        page.wait_for_timeout(3500)

        # Scroll through the rest of the plan (dock/boundary/schedule + rollout).
        page.evaluate("const el = document.querySelector('#result'); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'end' });")
        page.wait_for_timeout(3500)
    except Exception as e:
        _cap_log(f"[Warning] Advisor form demo skipped: {e}")


def _run_capture(url: str, out_name: str):
    try:
        from playwright.sync_api import sync_playwright
        _capture_job["status"] = "running"
        _cap_log("[Browser] Launching headless Chromium (Playwright)...")
        with tempfile.TemporaryDirectory() as tmp:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    record_video_dir=tmp,
                    record_video_size={"width": 1280, "height": 800},
                )
                ctx.add_init_script(_CURSOR_OVERLAY_JS)
                page = ctx.new_page()
                # Recording starts with page creation; waypoint timestamps are
                # measured from here so they line up with the video timeline.
                rec_t0 = time.monotonic()
                tour_waypoints = []
                _cap_log(f"[Browser] Navigating to: {url}")
                page.goto(url, wait_until="load", timeout=30000)
                _cap_log("[Browser] Page loaded. Viewport 1280x800. Recording active...")
                page.wait_for_timeout(2000)

                # Scripted tour: target-focused smooth scroll and organic Bezier cursor pointing.
                is_solutions_page = "solutions" in url.lower()

                if is_solutions_page:
                    targets_to_visit = [
                        {"query": "h1", "text": "Run revenue", "name": "Platform Hero"},
                        {"query": "h3", "text": "Revenue AI", "name": "Revenue AI Section"},
                        {"query": "h3", "text": "Customer AI", "name": "Customer AI Section"},
                        {"query": "h3", "text": "Operations AI", "name": "Operations AI Section"},
                        {"query": "h3", "text": "Physical AI", "name": "Physical AI Section"}
                    ]

                    steps = len(targets_to_visit)
                    for idx, target in enumerate(targets_to_visit):
                        _cap_log(f"[Agent] Section {idx+1}/{steps}: Showcasing {target['name']}...")
                        success = page.evaluate("""
                            ([query, text]) => {
                                const elements = Array.from(document.querySelectorAll(query));
                                let el = null;
                                if (!text) {
                                    el = elements[0];
                                } else {
                                    el = elements.find(e => e.textContent.trim().toLowerCase().includes(text.toLowerCase()));
                                }
                                if (el) {
                                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    window.__avip_current_tour_el = el;
                                    return true;
                                }
                                return false;
                            }
                        """, [target["query"], target["text"]])

                        page.wait_for_timeout(1400)

                        if success:
                            coords = page.evaluate("""
                                () => {
                                    const el = window.__avip_current_tour_el;
                                    if (!el) return null;
                                    const r = el.getBoundingClientRect();
                                    const scope = el.closest('section,article,div') || el.parentElement;
                                    const para = scope ? scope.querySelector('p') : null;
                                    return {
                                        x: Math.round(r.left + Math.min(r.width / 2, 200)),
                                        y: Math.round(r.top + r.height / 2),
                                        tag: el.tagName.toLowerCase(),
                                        text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
                                        context: para ? (para.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 240) : ''
                                    };
                                }
                            """)
                            if coords:
                                page.mouse.move(coords["x"], coords["y"])
                                page.evaluate(f"window.__avipMoveCursor && window.__avipMoveCursor({coords['x']}, {coords['y']})")
                                page.wait_for_timeout(1100)
                                page.evaluate("window.__avipPulse && window.__avipPulse()")
                                tour_waypoints.append({
                                    "t": round(time.monotonic() - rec_t0, 1),
                                    "name": target["name"],
                                    "tag": coords["tag"],
                                    "text": coords.get("text", ""),
                                    "context": coords.get("context", ""),
                                    "x": coords["x"], "y": coords["y"],
                                })
                                _cap_log(f"[Agent] Section {idx+1}/{steps}: pointing at <{coords['tag']}> and highlighting...")
                                page.wait_for_timeout(4000)
                            else:
                                page.wait_for_timeout(1500)
                        else:
                            _cap_log(f"[Warning] Could not find {target['name']} element.")
                            page.wait_for_timeout(1500)
                else:
                    # Full-page tour: every distinct visible heading becomes a tour
                    # stop (no count cap) so the narration covers the page in detail.
                    # Dedupe by text so repeated card titles don't stall the tour.
                    page.evaluate("""
                        () => {
                            const seen = new Set();
                            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4')).filter(el => {
                                const r = el.getBoundingClientRect();
                                if (r.width < 10 || r.height < 10) return false;
                                const t = el.textContent.trim().replace(/\\s+/g, ' ');
                                if (t.length <= 3) return false;
                                const key = t.toLowerCase().slice(0, 80);
                                if (seen.has(key)) return false;
                                seen.add(key);
                                return true;
                            });
                            window.__avip_generic_targets = headings;
                        }
                    """)
                    num_targets = page.evaluate("window.__avip_generic_targets ? window.__avip_generic_targets.length : 0") or 0

                    if num_targets > 0:
                        steps = num_targets
                        est_sec = round(steps * 7 + 5)
                        _cap_log(f"[Agent] Page mapped: {steps} distinct sections to showcase (full-page tour, ~{est_sec}s)...")
                        for idx in range(steps):
                            _cap_log(f"[Agent] Exploring section {idx+1}/{steps}...")
                            success = page.evaluate("""
                                (i) => {
                                    const el = window.__avip_generic_targets[i];
                                    if (el) {
                                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        window.__avip_current_tour_el = el;
                                        return true;
                                    }
                                    return false;
                                }
                            """, idx)

                            page.wait_for_timeout(1400)

                            if success:
                                coords = page.evaluate("""
                                    () => {
                                        const el = window.__avip_current_tour_el;
                                        if (!el) return null;
                                        const r = el.getBoundingClientRect();
                                        const scope = el.closest('section,article,div') || el.parentElement;
                                        const para = scope ? scope.querySelector('p') : null;
                                        return {
                                            x: Math.round(r.left + Math.min(r.width / 2, 200)),
                                            y: Math.round(r.top + r.height / 2),
                                            tag: el.tagName.toLowerCase(),
                                            text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
                                            context: para ? (para.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 240) : ''
                                        };
                                    }
                                """)
                                if coords:
                                    page.mouse.move(coords["x"], coords["y"])
                                    page.evaluate(f"window.__avipMoveCursor && window.__avipMoveCursor({coords['x']}, {coords['y']})")
                                    page.wait_for_timeout(1100)
                                    page.evaluate("window.__avipPulse && window.__avipPulse()")
                                    tour_waypoints.append({
                                        "t": round(time.monotonic() - rec_t0, 1),
                                        "name": coords.get("text", "") or f"Section {idx+1}",
                                        "tag": coords["tag"],
                                        "text": coords.get("text", ""),
                                        "context": coords.get("context", ""),
                                        "x": coords["x"], "y": coords["y"],
                                    })
                                    _cap_log(f"[Agent] Section {idx+1}/{steps}: pointing at <{coords['tag']}> and highlighting...")
                                    page.wait_for_timeout(4000)
                                else:
                                    page.wait_for_timeout(1500)
                            else:
                                page.wait_for_timeout(1500)
                    else:
                        height = page.evaluate("document.body.scrollHeight") or 800
                        steps = 5
                        for s in range(1, steps + 1):
                            y = int(height * s / (steps + 1))
                            page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
                            page.wait_for_timeout(1500)
                            tx = 200 + (s % 3) * 250
                            ty = 200 + (s % 2) * 200
                            page.mouse.move(tx, ty)
                            page.evaluate(f"window.__avipMoveCursor && window.__avipMoveCursor({tx}, {ty})")
                            page.wait_for_timeout(1100)
                            page.evaluate("window.__avipPulse && window.__avipPulse()")
                            _cap_log(f"[Agent] Exploring section {s}/{steps} (scroll to {y}px)...")
                            page.wait_for_timeout(2000)

                # If the page carries the advisor try-out form, run the
                # interactive segment: fill it on camera and show the real
                # Gemini-generated deployment plan in the recording.
                has_advisor = page.evaluate(
                    "!!(document.querySelector('#area') && document.querySelector('#run') && document.querySelector('#result'))")
                if has_advisor:
                    _demo_advisor_form(page, rec_t0, tour_waypoints)

                page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
                page.evaluate("window.__avipMoveCursor && window.__avipMoveCursor(150, 150)")
                page.wait_for_timeout(1500)

                # Persist the pointed targets as the narration waypoints: the
                # avatar narrates exactly what the cursor highlighted, in sync.
                if tour_waypoints:
                    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
                    manifest_path = VIDEO_DIR / out_name.replace("_recording.mp4", "_tour.json")
                    with open(manifest_path, "w", encoding="utf-8") as mf:
                        json.dump({"url": url, "file": out_name, "waypoints": tour_waypoints}, mf, indent=2)
                    _cap_log(f"[Recording] Tour manifest saved: {len(tour_waypoints)} narration waypoints → {manifest_path.name}")
                _cap_log("[Recording] Tour complete. Finalizing video container...")

                video = page.video
                ctx.close()
                webm_path = video.path()
                browser.close()

                VIDEO_DIR.mkdir(parents=True, exist_ok=True)
                out_path = VIDEO_DIR / out_name
                _cap_log("[FFmpeg] Transcoding WebM → MP4 (H.264, faststart)...")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(webm_path), "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
                    check=True, capture_output=True,
                )
        size_mb = round(out_path.stat().st_size / 1048576, 2)
        _cap_log(f"[System] Screen recorded successfully! File: {out_name} ({size_mb} MB)")
        _capture_job["status"] = "done"
    except Exception as e:
        _cap_log(f"[Error] Capture failed: {e}")
        _capture_job["status"] = "failed"


@router.post("/api/capture/run")
def capture_run(req: CaptureRequest):
    """Start a real screen-capture job for the given URL (one at a time)."""
    if _capture_job["status"] in ("starting", "running"):
        return {"status": "already_running", "file": _capture_job["file"]}
    url = (req.url or "").strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="URL must start with http(s)://")
    name = (req.file or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+_recording\.mp4", name):
        raise HTTPException(status_code=400, detail="Invalid recording file name.")
    _capture_job.update({"status": "starting", "file": name, "logs": []})
    threading.Thread(target=_run_capture, args=(url, name), daemon=True).start()
    return {"status": "started", "file": name}


@router.get("/api/capture/status")
def capture_status(offset: int = 0):
    """Poll real capture progress; `offset` skips log lines already received."""
    return {
        "status": _capture_job["status"],
        "file": _capture_job["file"],
        "logs": _capture_job["logs"][offset:],
        "total": len(_capture_job["logs"]),
    }
