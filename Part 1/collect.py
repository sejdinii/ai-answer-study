"""Collect answers from ChatGPT and Gemini with a real browser (Playwright).

Each answer is saved to answers/<platform>_qNN.json (+ .png screenshot) as soon as it is captured,
so a run can be stopped and resumed at any time. No CAPTCHA solving: blocked answers are retried
once after a cool-down, then left for the next run.
"""
import json
import random
import re
import time
from datetime import datetime
from urllib.parse import quote_plus, urlparse, urlencode, parse_qsl, urlunparse
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(__file__).parent / ".browser-profile"
PLATFORMS = {"chatgpt": "ChatGPT", "gemini": "Gemini"}
COOLDOWN_MINUTES = 5
GOOGLE_LINK = re.compile(r"google\.|gstatic\.|g\.co/|gemini\.google|youtube\.com/redirect")

EXTRACT_JS = """el => ({
  text: el.innerText,
  bold: [...el.querySelectorAll('strong, b')].map(b => b.innerText.trim()).filter(Boolean),
})"""


class Blocked(Exception):
    pass


def clean_url(url):
    """Drop tracking params (utm_*) and text fragments so the same page is counted once."""
    u = urlparse(url)
    query = urlencode([(k, v) for k, v in parse_qsl(u.query) if not k.startswith("utm_")])
    return urlunparse(u._replace(query=query, fragment=""))


def wait_until_done(page, answer, done_selector, timeout=180):
    """Wait until the platform shows its 'Copy' toolbar under the answer (= finished) and the text is stable.
    Pauses while the engine searches the web don't count as finished."""
    last, since, deadline = -1, time.time(), time.time() + timeout
    while time.time() < deadline:
        n = len(answer.inner_text())
        if n != last:
            last, since = n, time.time()
        elif n > 0 and time.time() - since >= 2 and page.locator(done_selector).count():
            return
        time.sleep(0.5)


def check_blocked(page):
    if "just a moment" in page.title().lower() or "/sorry/" in page.url or "challenge" in page.url:
        raise Blocked("bot check shown")


def dismiss_banners(page):
    for label in ("Reject non-essential", "Reject all"):
        button = page.get_by_role("button", name=label)
        if button.count():
            try:
                button.first.click(timeout=2000)
            except Exception:
                pass


def wait_for_answer(page, selector, resend=None, timeout=75):
    """Wait for the answer element, clearing popups and re-sending a stuck question along the way."""
    deadline, resent = time.time() + timeout, False
    while time.time() < deadline:
        check_blocked(page)
        if page.locator(selector).count():
            return page.locator(selector).last
        dismiss_banners(page)
        if resend and not resent and time.time() > deadline - timeout + 15:
            resend()
            resent = True
        time.sleep(1)
    raise TimeoutError("no answer appeared")


def ask_chatgpt(page, question):
    page.goto(f"https://chatgpt.com/?q={quote_plus(question)}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    def resend():  # question left in the composer (e.g. a popup blocked auto-send)
        box = page.locator("#prompt-textarea, div[contenteditable='true']").first
        if box.count() and question[:20] in (box.inner_text() or ""):
            box.press("Enter")
    answer = wait_for_answer(page, "[data-assistant-markdown]", resend)
    wait_until_done(page, answer, "[data-assistant-message-actions]")
    data = answer.evaluate(EXTRACT_JS)

    payloads = answer.locator("[data-assistant-sources-payload]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-assistant-sources-payload'))")
    sources = {}
    for raw in payloads:
        for s in json.loads(raw or "[]"):
            url = clean_url(s.get("url", ""))
            sources.setdefault(url, {"name": s.get("attribution", ""), "title": s.get("title", ""), "url": url})
    return answer, data, list(sources.values())


def ask_gemini(page, question):
    page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    check_blocked(page)
    dismiss_banners(page)
    box = page.locator("div[contenteditable='true']").first
    box.wait_for(timeout=30000)
    box.click()
    box.fill(question)
    page.keyboard.press("Enter")
    answer = wait_for_answer(page, "model-response message-content")
    wait_until_done(page, answer, "model-response message-actions")
    data = answer.evaluate(EXTRACT_JS)
    return answer, data, gemini_sources(page)


def gemini_sources(page):
    """Gemini shows sources as chips; opening a chip reveals its link."""
    sources = {}
    chips = page.locator("model-response source-inline-chip button")
    for i in range(min(chips.count(), 25)):
        chip = chips.nth(i)
        label = chip.get_attribute("aria-label") or ""
        match = re.search(r"citation from (.+?)\. Press", label)
        name = match.group(1) if match else chip.inner_text().split("\n")[0].strip()
        try:
            chip.scroll_into_view_if_needed(timeout=3000)
            chip.click(timeout=3000)
            chip.press("Enter")
            page.wait_for_timeout(1200)
            links = page.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => [a.href, a.innerText])")
            for href, text in links:
                if href.startswith("http") and not GOOGLE_LINK.search(href):
                    url = clean_url(href)
                    sources.setdefault(url, {"name": name, "title": text.strip(), "url": url})
            page.keyboard.press("Escape")
        except Exception:
            pass
        if name and not any(s["name"] == name for s in sources.values()):
            sources[f"name:{name}"] = {"name": name, "title": "", "url": ""}
    return list(sources.values())


ASK = {"chatgpt": ask_chatgpt, "gemini": ask_gemini}


def answer_path(out, platform, qid):
    return out / f"{platform}_q{qid:02d}.json"


def is_done(out, platform, qid):
    path = answer_path(out, platform, qid)
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("status") == "ok"


def run_jobs(page, out, jobs):
    failed = []
    for n, (qid, question, platform) in enumerate(jobs, 1):
        record = {"platform": platform, "question_id": qid, "question": question,
                  "collected_at": datetime.now().isoformat(timespec="seconds"),
                  "status": "ok", "text": "", "bold": [], "sources": [], "screenshot": ""}
        label = f"[{n}/{len(jobs)}] {PLATFORMS[platform]:<8} q{qid:02d}"
        try:
            answer, data, sources = ASK[platform](page, question)
            record.update(text=data["text"].strip(), bold=data["bold"], sources=sources)
            if not record["text"]:
                record["status"] = "empty"
            shot = answer_path(out, platform, qid).with_suffix(".png")
            try:
                answer.screenshot(path=str(shot), timeout=10000)
            except Exception:
                page.screenshot(path=str(shot))
            record["screenshot"] = shot.name
        except Blocked as e:
            record.update(status="blocked", error=str(e))
        except Exception as e:
            record.update(status="error", error=str(e).splitlines()[0][:200])
            try:
                page.screenshot(path=str(answer_path(out, platform, qid).with_suffix(".error.png")))
            except Exception:
                pass

        answer_path(out, platform, qid).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if record["status"] == "ok":
            print(f"{label}  ✓ {len(record['text']):,} chars, {len(record['sources'])} sources")
        else:
            print(f"{label}  ✗ {record['status']}: {record.get('error', '')}")
            failed.append((qid, question, platform))
        if n < len(jobs):
            time.sleep(random.uniform(4, 9))  # polite pacing, like a person reading
    return failed


def launch(p):
    for channel in ("chrome", "msedge", None):  # None = Playwright's own Chromium
        try:
            return p.chromium.launch_persistent_context(
                str(PROFILE), channel=channel, headless=False, locale="en-US",
                viewport={"width": 1280, "height": 900})
        except Exception:
            continue
    raise SystemExit("No browser found. Install Google Chrome, or run: python -m playwright install chromium")


def collect(audit_dir, questions):
    out = audit_dir / "answers"
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(qid, q, platform) for qid, q in enumerate(questions, 1) for platform in PLATFORMS]
    todo = [j for j in jobs if not is_done(out, j[2], j[0])]
    if not todo:
        print("All answers already collected.")
        return
    print(f"Collecting {len(todo)} answers (a browser window will open; leave it running)…")
    with sync_playwright() as p:
        context = launch(p)
        page = context.pages[0] if context.pages else context.new_page()
        failed = run_jobs(page, out, todo)
        if failed:
            blocked = any(json.loads(answer_path(out, pl, q).read_text(encoding="utf-8"))["status"] == "blocked"
                          for q, _, pl in failed)
            wait, unit = (COOLDOWN_MINUTES * 60, f"{COOLDOWN_MINUTES} minutes") if blocked else (20, "20 seconds")
            print(f"\n{len(failed)} answer(s) failed. Retrying once in {unit}…")
            time.sleep(wait)
            failed = run_jobs(page, out, failed)
        context.close()
    if failed:
        print(f"\n{len(failed)} answer(s) still missing. Run the same command again later to fill the gaps.")
