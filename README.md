# AI Visibility Audit

When buyers ask ChatGPT or Gemini for a recommendation, does a given company show up, where, and next to which competitors? This is a two-part case study: a working audit tool, and a plan for running it at scale.

The sample company is Skillsoft Percipio (corporate e-learning), audited against LinkedIn Learning, Udemy Business, Coursera for Business, Go1 and edX.

## Part 1: the audit tool (`Part 1/`)

You enter a company name and the questions its buyers ask, and the tool produces an HTML report.

- **Collect:** Playwright opens a real browser and asks each question in a fresh chat on the public, logged-out ChatGPT and Gemini. For every answer it saves the text, the brand names shown in bold, the sources cited and a screenshot.
- **Analyse:** plain text matching, with no LLM and no API keys. It records whether the client is mentioned, its rank among the brands named, its position in the answer, whether it is in bold, which competitors appear, and which domains are cited.
- **Report:** one HTML report per run, plus `results.csv` and `summary.json`. Runs can be resumed, and only missing answers are fetched again.

Two sample runs are included in `Part 1/audits/`. Each run asked 10 questions on both platforms, 20 answers in total. Setup and usage are in [`Part 1/README.md`](Part%201/README.md). It needs Python 3.10+, Chrome or Edge, and `pip install -r requirements.txt`.

## Part 2: running it at scale (`Part 2/PART2.pdf`)

A written plan for monitoring 500 brands across 3 AI platforms:

- **Cost model:** 225k answers a month if every brand gets its own 50 questions.
- **Reliability:** how answers vary between runs, and what breaks (blocking, page changes, outages).
- **The fix:** brands in the same industry share questions, so each question is asked once and every brand in the answer is scored. That cuts the volume to about 72k answers a month, roughly 3× cheaper, while each brand gets more than twice as many questions.
- **Trust:** trial runs to measure answer variation, reporting how often a brand appears rather than single answers, and statistical tests that flag only real changes.

## Stack

Python, Playwright, HTML report templates.
