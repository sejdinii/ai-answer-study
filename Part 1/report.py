"""Build report.html from the analysis: numbers poured into an HTML template (no LLM)."""
import html
import re
from datetime import date

from analyze import load_answers
from collect import PLATFORMS

CSS = """
:root { --bg:#FAF9F5; --surface:#F0EEE6; --card:#FFFFFF; --text:#141413; --muted:#6B6A65;
        --border:#E8E6DC; --accent:#D97757; --accent-soft:#F6DED3; --comp-soft:#E3E1D8; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.6 "Source Serif 4", Georgia, serif; }
main { max-width:980px; margin:0 auto; padding:48px 20px 80px; }
h1 { font-size:2.2rem; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em; }
h2 { font-size:1.35rem; font-weight:600; margin:48px 0 14px; padding-top:20px; border-top:1px solid var(--border); }
h3 { font-size:1.05rem; margin:28px 0 8px; }
.sub, .muted, th, .label, summary small { color:var(--muted); }
.sub { font-family:Inter, system-ui, sans-serif; font-size:.9rem; }
.lead { font-size:1.12rem; background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px 22px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:12px; margin-top:20px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }
.kpi b { display:block; font-size:1.9rem; font-weight:600; line-height:1.2; }
.label, table, summary, .chip { font-family:Inter, system-ui, sans-serif; font-size:.85rem; }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--border); vertical-align:top; }
th { font-weight:500; background:var(--surface); }
tr:last-child td { border-bottom:none; }
td.c { text-align:center; white-space:nowrap; }
.yes { background:var(--accent-soft); color:#8A3B1F; font-weight:600; border-radius:6px; padding:2px 8px; }
.no { color:var(--muted); }
.bar { height:10px; background:var(--comp-soft); border-radius:5px; }
.bar.client { background:var(--accent); }
tr.client td { font-weight:600; }
details { background:var(--card); border:1px solid var(--border); border-radius:12px; margin:8px 0; }
summary { cursor:pointer; padding:12px 16px; }
.answer { white-space:pre-wrap; padding:4px 18px 8px; font-size:.97rem; }
.sources { padding:0 18px 16px; font-family:Inter, system-ui, sans-serif; font-size:.82rem; }
.sources a { color:var(--text); }
mark.client { background:var(--accent-soft); color:#8A3B1F; font-weight:600; padding:0 2px; border-radius:3px; }
mark.comp { background:var(--comp-soft); color:inherit; padding:0 2px; border-radius:3px; }
.chip { display:inline-block; border:1px solid var(--border); border-radius:99px; padding:1px 9px; margin:2px 2px 0 0; background:var(--surface); }
.wrap { overflow-x:auto; }
ul { padding-left:20px; }
"""


def esc(s):
    return html.escape(str(s))


def pct(x):
    return f"{round(x * 100)}%"


def highlight(text, client_names, brand_variants):
    """Escape the answer text and wrap brand names in coloured <mark> tags."""
    client_set = {n.lower() for n in client_names}
    alts = [f"(?i:{re.escape(html.escape(n))})" for n in client_names]
    alts += [re.escape(html.escape(v)) for v in brand_variants]
    alts.sort(key=len, reverse=True)
    rx = re.compile(rf"(?<!\w)(?:{'|'.join(alts)})(?!\w)")

    def mark(m):
        kind = "client" if html.unescape(m.group(0)).lower() in client_set else "comp"
        return f'<mark class="{kind}">{m.group(0)}</mark>'
    return rx.sub(mark, html.escape(text))


def summary_text(s):
    client, n = esc(s["client"]), s["answers"]
    per_platform = ", ".join(f"{PLATFORMS[p]} {v['mentioned']}/{v['answers']}" for p, v in s["platforms"].items())
    parts = [f"<b>{client}</b> was mentioned in <b>{s['mentioned']} of {n}</b> AI answers ({pct(s['rate'])}): {per_platform}."]
    if s["mentioned"]:
        parts.append(f"When mentioned, it was on average brand <b>#{s['avg_rank']}</b> in the answer "
                     f"and was featured in bold {s['featured']} time(s).")
    top = next((b for b in s["leaderboard"] if not b["is_client"]), None)
    if top:
        parts.append(f"The most-mentioned competitor was <b>{esc(top['name'])}</b> ({top['answers']}/{n} answers).")
    parts.append(f"{client}'s own website was cited as a source in <b>{s['cited']}</b> answer(s).")
    if s["top_sources"]:
        t = s["top_sources"][0]
        parts.append(f"The most-cited source was <b>{esc(t['domain'])}</b> ({t['answers']} answers).")
    if s["branded"]:
        parts.append(f"<span class='muted'>Without the question(s) that name the client: mentioned in "
                     f"{s['unbranded_mentioned']} of {s['unbranded_answers']} answers.</span>")
    if s["failed"]:
        parts.append(f"<span class='muted'>{s['failed']} answer(s) could not be collected and are excluded.</span>")
    return " ".join(parts)


def build_report(audit_dir, config, rows, summary, brands):
    s = summary
    client_names = config["company"]
    variants = [v for b in brands for v in b["variants"]]
    answers = {(a["platform"], a["question_id"]): a for a in load_answers(audit_dir)}
    by_key = {(r["platform"], r["question_id"]): r for r in rows}
    platforms = list(s["platforms"])
    questions = list(enumerate(config["questions"], 1))

    kpis = [(f"{s['mentioned']}/{s['answers']}", f"answers mention {esc(s['client'])} ({pct(s['rate'])})"),
            (f"#{s['avg_rank']}" if s["avg_rank"] else "–", "average brand rank when mentioned"),
            (pct(s["share_of_voice"]), "share of voice among all brands named"),
            (str(s["featured"]), "times featured in bold"),
            (str(s["cited"]), "answers citing the client's website")]
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span class="label">{l}</span></div>' for v, l in kpis)

    plat_rows = "".join(
        f"<tr><td>{PLATFORMS[p]}</td><td class='c'>{v['answers']}</td><td class='c'>{v['mentioned']} ({pct(v['rate'])})</td>"
        f"<td class='c'>{'#' + str(v['avg_rank']) if v['avg_rank'] else '–'}</td><td class='c'>{v['cited']}</td>"
        f"<td class='c'>{v['failed']}</td></tr>" for p, v in s["platforms"].items())

    def cell(r):
        if not r or r["status"] != "ok":
            return "<td class='c no'>n/a</td>"
        if r["branded"] and r["mentioned"]:
            return f"<td class='c'><span class='yes'>#{r['rank']}</span> <small class='muted'>(named in question)</small></td>"
        if r["mentioned"]:
            return f"<td class='c'><span class='yes'>#{r['rank']}</span></td>"
        return "<td class='c no'>·</td>"
    matrix = "".join(f"<tr><td>{qid}. {esc(q)}</td>" + "".join(cell(by_key.get((p, qid))) for p in platforms) + "</tr>"
                     for qid, q in questions)

    n = max(s["answers"], 1)
    board = "".join(
        f"<tr class='{'client' if b['is_client'] else ''}'><td>{esc(b['name'])}</td><td class='c'>{b['answers']}</td>"
        f"<td style='width:40%'><div class='bar {'client' if b['is_client'] else ''}' style='width:{b['answers'] / n * 100:.0f}%'></div></td>"
        f"<td class='c'>{'#' + str(b['avg_rank']) if b['avg_rank'] else '–'}</td></tr>" for b in s["leaderboard"][:15])

    sources = "".join(
        f"<tr><td>{esc(t['domain'])}</td><td>{esc(t['type'])}</td><td class='c'>{t['answers']}</td>"
        f"<td>{', '.join(PLATFORMS[p] for p in t['platforms'])}</td></tr>" for t in s["top_sources"][:15])

    detail = []
    for qid, q in questions:
        detail.append(f"<h3>{qid}. {esc(q)}</h3>")
        for p in platforms:
            r, a = by_key.get((p, qid)), answers.get((p, qid))
            if not r or not a:
                continue
            if r["status"] != "ok":
                detail.append(f"<details><summary>{PLATFORMS[p]} <small>— not collected ({esc(r['status'])})</small></summary></details>")
                continue
            status = f"mentioned, brand #{r['rank']}" if r["mentioned"] else "not mentioned"
            src = "".join(
                f"<li><a href='{esc(x['url'])}' target='_blank'>{esc(x['title'] or x['domain'])}</a> <span class='muted'>· {esc(x['domain'])}</span></li>"
                if x.get("url") else f"<li>{esc(x['name'])}</li>" for x in r["sources"])
            shot = f" · <a href='answers/{esc(a['screenshot'])}' target='_blank'>screenshot</a>" if a.get("screenshot") else ""
            detail.append(
                f"<details><summary>{PLATFORMS[p]} <small>— {status} · {len(r['sources'])} sources</small></summary>"
                f"<div class='answer'>{highlight(a['text'], client_names, variants)}</div>"
                f"<div class='sources'><b>Sources</b>{shot}<ul>{src or '<li class=muted>none shown</li>'}</ul></div></details>")

    collected = sorted(a["collected_at"][:10] for a in answers.values())
    when = collected[0] if collected else date.today().isoformat()
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Visibility: {esc(s['client'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<h1>AI Visibility: {esc(s['client'])}</h1>
<p class="sub">{len(questions)} buyer questions · {', '.join(PLATFORMS[p] for p in platforms)} · collected {when} ·
also tracked as: {esc(', '.join(client_names))}</p>
<p class="lead">{summary_text(s)}</p>
<div class="kpis">{kpi_html}</div>

<h2>By platform</h2>
<div class="wrap"><table><tr><th>Platform</th><th>Answers</th><th>Mentioned</th><th>Avg rank</th><th>Client cited</th><th>Failed</th></tr>{plat_rows}</table></div>

<h2>Question by question</h2>
<p class="muted">#N = the client was the Nth brand named in the answer. · = not mentioned.</p>
<div class="wrap"><table><tr><th>Question</th>{''.join(f"<th class='c'>{PLATFORMS[p]}</th>" for p in platforms)}</tr>{matrix}</table></div>

<h2>Who AI recommends</h2>
<p class="muted">Brands named across all answers, with their average position. Highlighted row = client.</p>
<div class="wrap"><table><tr><th>Brand</th><th>Answers</th><th></th><th>Avg rank</th></tr>{board}</table></div>

<h2>Sources AI relies on</h2>
<div class="wrap"><table><tr><th>Domain</th><th>Type</th><th>Answers</th><th>Platforms</th></tr>{sources or '<tr><td colspan=4 class=muted>No sources shown</td></tr>'}</table></div>

<h2>All answers</h2>
<p class="muted"><mark class="client">client</mark> <mark class="comp">competitor</mark></p>
{''.join(detail)}

<h2>Method &amp; limitations</h2>
<ul>
<li>Answers were collected from the public, logged-out web versions of each platform with a real browser (Playwright), one new chat per question.</li>
<li>All metrics are computed with plain text matching and counting: no language model is used in the analysis. Competitors are detected from the brand names the engines put in bold.</li>
<li>AI answers vary between runs, over time and by location (detected from the IP address). Treat this as a snapshot; re-run the same audit to track change.</li>
<li>Google AI Overviews block automated access, so Gemini is used as Google's AI surface. AI Overviews can be added through a SERP API.</li>
</ul>
</main></body></html>"""
    path = audit_dir / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
