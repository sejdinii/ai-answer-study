# AI Visibility Audit

Enter a company and the questions buyers ask. The script asks **ChatGPT** and **Gemini**, then reports
whether the company is mentioned, where it appears, which competitors are named, and which sources are cited.

Sample client: **Skillsoft Percipio** (corporate e-learning content library), with LinkedIn Learning, Udemy
Business, Coursera for Business, Go1 and edX as the main competitors.

## Run it

Requirements: Python 3.10+ and Google Chrome (or Microsoft Edge). No API keys, accounts or database.

```
pip install -r requirements.txt
python audit.py              # type a company name + questions
python audit.py --sample     # run the Skillsoft Percipio sample
```

Or double-click `start.bat` (Windows) / `start.command` (Mac; run `chmod +x start.command` once).

A browser window opens and asks each question by itself (leave it running, ~1 minute per question).
When it finishes, `report.html` opens in your browser.

Each run gets its own folder:

```
audits/skillsoft_2026-10-03_1412/
├─ input.json     company + questions (re-run with: python audit.py input.json)
├─ answers/       every answer: text, bold brand names, sources, screenshot
├─ results.csv    one row per answer
├─ summary.json
└─ report.html
```

`python audit.py audits/<folder>` resumes a run: it only fetches missing answers and rebuilds the report.

## How it works

| Step | File | What happens |
|---|---|---|
| 1. Input | `audit.py` | Company name(s) + questions, saved to `input.json` |
| 2. Collect | `collect.py` | Playwright opens a real browser, asks each question in a new chat on the public, logged-out ChatGPT and Gemini, waits for the answer to finish, saves text, bold names, sources and a screenshot |
| 3. Analyze | `analyze.py` | Text matching and counting (no LLM) |
| 4. Report | `report.py` | Numbers poured into an HTML template |

**What is recorded for each answer**

| Field | How |
|---|---|
| Client mentioned | Search for the company names (whole word, any case) |
| Where | Brand rank (the client is the Nth brand named), position in the text (0 = top, 1 = end), featured in bold or not |
| Competitors | Brand names the engines put in bold, merged ("Udemy" + "Udemy Business"), then searched for in every answer |
| Sources | The links each platform shows (ChatGPT citation pills, Gemini source chips), grouped by domain and type |
