"""Turn collected answers into metrics. No LLM: only text matching and counting.

Per answer: is the client mentioned, where (brand rank, position in text, featured in bold),
which competitors appear, which sources are cited. Competitors are detected from the brand
names the AI engines put in bold, then searched for in every answer.
"""
import csv
import json
import re
from collections import Counter
from statistics import mean
from urllib.parse import urlparse

# Bold labels that are not brands ("**Best for:** …")
LABELS = {
    "best for", "best overall", "best fit", "ideal for", "good for", "great for", "key strengths", "strengths",
    "key features", "features", "notable features", "standout features", "why it stands out", "consideration",
    "considerations", "pros", "cons", "drawbacks", "limitations", "weaknesses", "pricing", "price", "cost",
    "budget", "summary", "overview", "recommendation", "recommendations", "bottom line", "verdict", "note",
    "tip", "example", "examples", "option", "options", "top pick", "top picks", "quick answer", "short answer",
    "my take", "tl;dr", "yes", "no", "why", "how", "what", "who", "when", "integration", "integrations",
    "compliance", "leadership", "soft skills", "content", "platform", "platforms", "lms", "lxp", "ai", "scorm",
    "hris", "enterprise", "enterprises", "smb", "smbs", "use case", "use cases", "best choice", "alternatives",
    "comparison", "conclusion", "final thoughts", "watch out", "caveat", "important", "step", "goal",
}
CONNECTORS = {"for", "of", "and", "by", "at", "the", "de", "la", "&"}
# Ordinary words: a bold phrase made only of these is a heading, not a brand ("Massive Content Library")
GENERIC = set("""
a an the for of and with in on to by at or vs it its if you your our we this that these those other others more also
best better top leading popular notable honorable mentions mention great good excellent strong massive deep broad wide
fast quick short simple easy robust comprehensive extensive flexible custom global personalized personalised modern
enterprise enterprises corporate company companies business businesses organization organizations organisation
small medium large mid size sized budget friendly affordable premium free trial cost costs price pricing value
learning training skills skill soft hard tech technical technology engineering it data science analytics reporting
tracking compliance leadership management development coaching mentoring onboarding upskilling reskilling
content library libraries catalog catalogue course courses quality varies variety range depth breadth scale
scalability flexibility engagement experience user users interface mobile platform platforms tool tools solution
solutions system systems software provider providers vendor vendors option options alternative alternatives choice
choices pick picks winner recommendation recommendations approach strategy strategies step steps tip tips
why what how when who which ai powered driven based assessment assessments path paths program programs programme
cohort live instructor led self paced video videos microlearning gamification social collaborative blended hybrid
virtual classroom workshop workshops emotional intelligence communication conflict resolution feedback performance
manager managers employee employees team teams people staff workforce talent hr lms lxp scorm hris sso api
academic professional university universities credential credentials certificate certificates certification
certifications degree degrees expert experts industry industries specialized specialised niche general overall
final thoughts conclusion summary overview key takeaways takeaway bottom line verdict cons pros considerations
consideration features feature standout stands out unique selling point points strengths weaknesses limitations
drawbacks downsides caveats caveat watch important note quick answer comparison table criteria factors factor
ideal fit use case cases need needs want worth consider administrative complexity multimodal potential dealbreakers
dealbreaker integration integrations implementation setup support customer service security privacy ease
innovation insights insight trends future roi impact results outcomes goals goal growth culture change
europe emea apac americas asia us usa uk germany dach north south america
""".split())
REVIEW_SITES = ("g2.com", "capterra", "trustradius", "gartner", "softwareadvice", "getapp", "trustpilot",
                "peerspot", "selecthub")
COMMUNITY_SITES = ("reddit.com", "quora.com", "youtube.com", "medium.com", "linkedin.com")


def load_answers(audit_dir):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((audit_dir / "answers").glob("*.json"))]


def clean_candidate(s):
    s = re.sub(r"[™®]", "", s)
    s = s.replace("’", "'")
    s = re.sub(r"^\d+[.)]\s*", "", s.strip())
    s = re.sub(r"^(and|or)\s+", "", s)
    s = s.strip(" :;,.!?-–—•*·()[]\"'“”‘’")
    words = s.split()
    if not words or len(words) > 4 or len(s) > 40 or ":" in s or s.lower() in LABELS:
        return None
    if all(re.sub(r"[^a-z0-9&]", "", w.lower()) in GENERIC | {"", "&"} for w in words):
        return None
    if words[0].lower() == "for" or any(w.isdigit() for w in words):
        return None
    if len(words) == 1 and (len(s) <= 2 or (s.isupper() and len(s) <= 4)):  # "So", "VR", "APAC"
        return None
    if not any(c.isupper() for c in words[0]):
        return None
    if any(w.lower() not in CONNECTORS and not any(c.isupper() or c.isdigit() for c in w) for w in words[1:]):
        return None
    return s


def candidates_from_bold(bold_texts):
    for text in bold_texts:
        for part in re.split(r",\s*|\s+(?:and|or|vs\.?|versus|&)\s+|\s*/\s*|\n", text):
            if (name := clean_candidate(part)):
                yield name


def ordinary_words(answers):
    """Words written in lowercase somewhere in the answers ("customization") are ordinary words, not brands."""
    words = set(GENERIC)
    for a in answers:
        words |= set(re.findall(r"(?<![\w.@/])[a-z][a-z0-9'’-]*(?![\w@/]|\.[a-z])", a.get("text", "")))
    return words


def looks_like_brand(name, ordinary):
    """A brand starts with a word that is never written in lowercase: Udemy Business, Harvard ManageMentor, Go1."""
    words = name.split()
    first = words[0].lower()
    if first in ordinary:
        return False
    if len(words) == 1 and words[0][1:].islower() and re.search(r"(ing|tion|ence|ance|ness|ment|ity|based)$", first):
        return False
    return True


def group_variants(counts):
    """Merge 'Udemy' + 'Udemy Business' into one brand (word-prefix rule)."""
    groups = []
    for name in sorted(counts, key=lambda n: (len(n.split()), n)):
        tokens = name.lower().split()
        for g in groups:
            base = g[0].lower().split()
            if tokens[:len(base)] == base:
                g.append(name)
                break
        else:
            groups.append([name])
    return [{"name": max(g, key=lambda n: (counts[n], len(n))), "variants": g} for g in groups]


def pattern(variants, ignore_case=False):
    alts = "|".join(re.escape(v).replace("'", "['’]") for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE if ignore_case else 0)


def domain_of(source):
    if source.get("url"):
        return urlparse(source["url"]).netloc.lower().removeprefix("www.")
    return source.get("name", "").lower()


def domain_type(domain, url, client_tokens, brand_tokens):
    if any(t in domain for t in client_tokens):
        return "client"
    if any(s in domain for s in REVIEW_SITES):
        return "review site"
    if "linkedin.com" in domain and "/learning" in url:
        return "competitor"
    if any(s in domain for s in COMMUNITY_SITES):
        return "community"
    if any(t in domain for t in brand_tokens):
        return "competitor"
    return "other"


def token(name):
    return re.sub(r"[^a-z0-9]", "", name.lower().split()[0])


def analyze(audit_dir, config):
    answers = load_answers(audit_dir)
    client_names = config["company"]
    client_re = pattern(client_names, ignore_case=True)
    client_tokens = [t for t in (re.sub(r"[^a-z0-9]", "", n.lower()) for n in client_names) if len(t) >= 3]
    ignore = {i.lower() for i in config.get("ignore", [])}

    # 1. Brand list: bold names from all answers + optional known competitors
    ordinary = ordinary_words(answers)
    counts = Counter(c for a in answers for c in candidates_from_bold(a.get("bold", []))
                     if looks_like_brand(c, ordinary))
    for name in config.get("competitors", []):
        counts[name] += 0
    counts = Counter({n: c for n, c in counts.items() if not client_re.search(n) and n.lower() not in ignore})
    brands = group_variants(counts)
    for b in brands:
        b["re"] = pattern(b["variants"])
    brand_tokens = [t for t in (token(b["name"]) for b in brands) if len(t) >= 4]

    # 2. Per-answer metrics
    rows = []
    for a in answers:
        text = a.get("text", "")
        row = {"question_id": a["question_id"], "question": a["question"], "platform": a["platform"],
               "status": a["status"], "branded": bool(client_re.search(a["question"])), "mentioned": False, "names_used": "", "mentions": 0, "rank": "",
               "brands_in_answer": 0, "position_in_text": "", "featured": False, "cited": False,
               "competitors": [], "order": [], "sources": []}
        if a["status"] == "ok":
            positions = {}
            for b in brands:
                if b["re"].search(a["question"]):  # named in the question itself: not a recommendation
                    continue
                if (m := b["re"].search(text)):
                    positions[b["name"]] = m.start()
            hits = list(client_re.finditer(text))
            row["competitors"] = sorted(positions, key=positions.get)
            row["brands_in_answer"] = len(positions) + (1 if hits else 0)
            order = dict(positions, **({config["company"][0]: hits[0].start()} if hits else {}))
            row["order"] = sorted(order, key=order.get)
            if hits:
                first = hits[0].start()
                used = {n for n in client_names for h in hits if h.group(0).lower() == n.lower()}
                row.update(mentioned=True, mentions=len(hits), names_used=", ".join(sorted(used)),
                           rank=1 + sum(p < first for p in positions.values()),
                           position_in_text=round(first / max(len(text), 1), 2),
                           featured=any(client_re.search(b) for b in a.get("bold", [])))
            for s in a.get("sources", []):
                d = domain_of(s)
                row["sources"].append({**s, "domain": d,
                                       "type": domain_type(d, s.get("url", ""), client_tokens, brand_tokens)})
            row["cited"] = any(s["type"] == "client" for s in row["sources"])
        rows.append(row)

    summary = summarize(rows, brands, config)
    write_csv(audit_dir, rows)
    (audit_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary, brands


def summarize(rows, brands, config):
    collected = [r for r in rows if r["status"] == "ok"]
    ok = collected
    # Secondary figure: questions that don't name the client ("Is Skillsoft worth it?" always mentions it)
    unbranded = [r for r in collected if not r["branded"]]
    mentioned = [r for r in ok if r["mentioned"]]
    client = config["company"][0]

    def rate(part, whole):
        return round(len(part) / len(whole), 3) if whole else 0

    platforms = {}
    for p in sorted({r["platform"] for r in rows}):
        p_ok = [r for r in ok if r["platform"] == p]
        p_all = [r for r in rows if r["platform"] == p]
        p_m = [r for r in p_ok if r["mentioned"]]
        platforms[p] = {"answers": len(p_ok), "mentioned": len(p_m), "rate": rate(p_m, p_ok),
                        "avg_rank": round(mean(r["rank"] for r in p_m), 1) if p_m else None,
                        "cited": sum(r["cited"] for r in p_ok), "failed": sum(r["status"] != "ok" for r in p_all)}

    board = Counter(c for r in ok for c in r["competitors"])
    ranks = {}
    for r in ok:
        for i, c in enumerate(r["order"]):
            ranks.setdefault(c, []).append(i + 1)
    leaderboard = [{"name": client, "answers": len(mentioned), "is_client": True,
                    "avg_rank": round(mean(r["rank"] for r in mentioned), 1) if mentioned else None}]
    leaderboard += [{"name": n, "answers": c, "is_client": False, "avg_rank": round(mean(ranks[n]), 1)}
                    for n, c in board.items()]
    leaderboard.sort(key=lambda x: (-x["answers"], x["avg_rank"] or 99))

    total_appearances = sum(board.values()) + len(mentioned)
    domains = Counter()
    domain_info = {}
    for r in ok:
        for d in {s["domain"]: s for s in r["sources"]}.values():
            domains[d["domain"]] += 1
            info = domain_info.setdefault(d["domain"], {"type": d["type"], "platforms": set()})
            info["platforms"].add(r["platform"])
    top_sources = [{"domain": d, "answers": n, "type": domain_info[d]["type"],
                    "platforms": sorted(domain_info[d]["platforms"])} for d, n in domains.most_common(20)]

    return {
        "client": client, "answers": len(ok), "failed": len(rows) - len(collected),
        "branded": len(collected) - len(unbranded),
        "unbranded_answers": len(unbranded), "unbranded_mentioned": sum(r["mentioned"] for r in unbranded),
        "mentioned": len(mentioned), "rate": rate(mentioned, ok),
        "avg_rank": round(mean(r["rank"] for r in mentioned), 1) if mentioned else None,
        "featured": sum(r["featured"] for r in mentioned), "cited": sum(r["cited"] for r in ok),
        "share_of_voice": round(len(mentioned) / total_appearances, 3) if total_appearances else 0,
        "platforms": platforms, "leaderboard": leaderboard, "top_sources": top_sources,
        "brands_detected": [b["name"] for b in brands if board.get(b["name"])],
    }


def write_csv(audit_dir, rows):
    with open(audit_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "question", "platform", "status", "client_mentioned", "names_used", "mentions",
                    "brand_rank", "brands_in_answer", "position_in_text", "featured_in_bold", "client_cited",
                    "competitors", "source_domains"])
        for r in rows:
            w.writerow([r["question_id"], r["question"], r["platform"], r["status"], r["mentioned"],
                        r["names_used"], r["mentions"], r["rank"], r["brands_in_answer"], r["position_in_text"],
                        r["featured"], r["cited"], "; ".join(r["competitors"]),
                        "; ".join(dict.fromkeys(s["domain"] for s in r["sources"]))])
