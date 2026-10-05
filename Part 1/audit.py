"""AI Visibility Audit: enter a company and questions, get a report.

  python audit.py                  ask for company name + questions
  python audit.py --sample         run the Skillsoft Percipio sample
  python audit.py input.json       start a new audit from a saved input file
  python audit.py audits/<folder>  resume an audit (fills missing answers, rebuilds the report)
"""
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SAMPLE = ROOT / "samples" / "skillsoft.json"


def ask_input():
    print("AI Visibility Audit\n───────────────────")
    names = [n.strip() for n in input("Company name (separate other names with commas): ").split(",") if n.strip()]
    print("Questions, one per line (empty line to finish):")
    questions = []
    while (line := input("> ").strip()):
        questions.append(line)
    if not names or not questions:
        sys.exit("Need a company name and at least one question.")
    return {"company": names, "questions": questions}


def new_audit(config):
    slug = re.sub(r"[^a-z0-9]+", "-", config["company"][0].lower()).strip("-")
    folder = ROOT / "audits" / f"{slug}_{datetime.now():%Y-%m-%d_%H%M}"
    folder.mkdir(parents=True)
    (folder / "input.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg and Path(arg).is_dir():
        folder = Path(arg).resolve()
        config = json.loads((folder / "input.json").read_text(encoding="utf-8"))
    else:
        if arg == "--sample":
            arg = SAMPLE
        config = json.loads(Path(arg).read_text(encoding="utf-8")) if arg else ask_input()
        folder = new_audit(config)

    from collect import collect          # imported here so --help style errors stay fast
    from analyze import analyze
    from report import build_report

    print(f"\nAudit folder: {folder}")
    collect(folder, config["questions"])
    rows, summary, brands = analyze(folder, config)
    path = build_report(folder, config, rows, summary, brands)

    print(f"\n✓ {summary['client']} mentioned in {summary['mentioned']}/{summary['answers']} answers"
          + (f" · average brand rank #{summary['avg_rank']}" if summary["avg_rank"] else ""))
    print(f"Brands detected: {', '.join(summary['brands_detected']) or 'none'}")
    print("  (wrong ones? add them to \"ignore\" in input.json and run: python audit.py <audit folder>)")
    print(f"✓ Report: {path}")
    webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
