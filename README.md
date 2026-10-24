# AI News Aggregator

A free, automated daily news digest focused on healthcare payments, consumer
payments, product management, and AI adoption for PMs. Runs in GitHub Actions,
uses Gemini to filter and annotate articles, emails the result via Brevo SMTP,
and commits a dated Markdown archive back to the repo.

## Zero recurring cost

Every piece of the stack is on a free forever tier:

- **GitHub Actions**: free unlimited standard-runner minutes on **public** repos (this repo is intended to be public). On a private repo you'd get 2,000 min/month free, which is still plenty for ~60 min/month of use.
- **Gemini API**: `gemini-3.5-flash-lite` is $0 for input and output tokens on the Free Tier.
- **Brevo**: 300 emails/day forever free. One caveat: free-tier emails always include a small "Sent with Brevo" footer sticker. Fine for a digest you send to yourself; the only way to remove it is a paid add-on, which we don't use.

Keep the GitHub repo **public** and don't put a payment method on your GitHub account to guarantee no run can ever cost money.

## Architecture

- **Sources**: RSS feeds listed in [`feeds.yaml`](feeds.yaml).
- **Fetcher**: [`aggregator/feeds.py`](aggregator/feeds.py) — newest 5 per feed, 48h freshness window, dedup against `history.json`.
- **Curation**: [`aggregator/ai.py`](aggregator/ai.py) — one batched `gemini-3.5-flash-lite` call per category returning `{relevant, why_it_matters}` per article.
- **Rendering**: [`aggregator/render.py`](aggregator/render.py) + Jinja2 templates in [`templates/`](templates).
- **Email**: [`aggregator/email_send.py`](aggregator/email_send.py) — Brevo SMTP (`smtp-relay.brevo.com:587`, STARTTLS).
- **Archive**: one Markdown file per day in [`digests/`](digests), committed by the workflow.
- **History**: `history.json` (URL sha1 + ISO timestamp, pruned to 30 days) stored in **GitHub Actions cache**, not in the git repo. Each run restores the most recent `history-*` cache and saves a new one keyed by `run_id`. Locally the same file is a side-effect in your working tree and is gitignored.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your values
set -a && source .env && set +a
python aggregator.py --dry-run
```

- `--dry-run` fetches + curates and prints the Markdown digest to stdout. No email, no archive, no history update.
- `--skip-email` runs end-to-end but skips the SMTP call (useful if you want to see the archive without sending mail).
- Without `GEMINI_API_KEY`, the AI filter is skipped gracefully: all articles pass through without a "why it matters" line.
- Locally, `history.json` is created in the repo root on first full run. It's gitignored.

## GitHub setup

### 1. Create the repo as public

For unlimited free Actions minutes, keep the repo **public** when you create it. The digest content (industry news summaries) is not sensitive.

### 2. Required repository secrets

Go to **Settings -> Secrets and variables -> Actions** and add:

| Secret              | Where to find it                                                          |
| ------------------- | ------------------------------------------------------------------------- |
| `GEMINI_API_KEY`    | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) -> **Create API key**. New projects should pick `gemini-3.5-flash-lite` or `gemini-3.8-flash` (both free). |
| `BREVO_SMTP_LOGIN`  | Brevo dashboard -> SMTP & API -> SMTP. The numeric login (e.g. `9a1b2c`). |
| `BREVO_SMTP_KEY`    | Same page. The generated SMTP key (not the REST API key).                 |
| `SENDER_EMAIL`      | A Brevo-verified sender address (see below).                              |
| `RECIPIENT_EMAIL`   | The inbox you want the digest delivered to.                               |

### 3. Verify your Brevo sender

Brevo rejects mail from unverified senders. In the Brevo dashboard:

1. Senders, Domains & Dedicated IPs -> Senders -> **Add a sender**.
2. Enter the same address you'll use as `SENDER_EMAIL`.
3. Click the confirmation link Brevo emails you.

For better deliverability, also authenticate the domain (DKIM + SPF) under
**Domains**. Not strictly required for the free tier but strongly recommended.

The free plan also includes a non-removable "Sent with Brevo" footer on every email. Expected and harmless for a self-addressed digest.

### 4. First run

1. Push this repo to GitHub (public).
2. Ensure the workflow permissions allow writes: **Settings -> Actions -> General -> Workflow permissions -> "Read and write permissions"**. (The workflow also declares `permissions: contents: write` explicitly, which is needed to push the digest archive.)
3. Actions tab -> **Daily News Digest** -> **Run workflow** to trigger manually.
4. On success, check your inbox and confirm a new file under `digests/` was committed. The dedup state lives in the Actions cache (**Actions -> Caches**) under keys like `history-<run-id>`.

## Schedule and timezone

The cron is `0 13 * * *` UTC, which is 08:00 America/New_York during EST. Two things to know:

- GitHub Actions cron is **UTC only** and does **not** honor DST. During EDT (March to November) the digest will arrive at 09:00 local unless you change the cron line to `0 12 * * *`.
- Edit the line in [`.github/workflows/daily_news.yml`](.github/workflows/daily_news.yml) for any other timezone.

## Extending

- **Add sources**: append to [`feeds.yaml`](feeds.yaml). Use the declared category names (`Healthcare Payments`, `Consumer Payments`, `Product Management & AI`) to keep the category ordering in the rendered digest, or invent new ones — they'll render at the end.
- **Change the relevance criteria**: edit `_PROMPT_TEMPLATE` and `TOPICS` in [`aggregator/ai.py`](aggregator/ai.py).
- **Change the Gemini model**: update `MODEL_NAME` in [`aggregator/ai.py`](aggregator/ai.py). `gemini-3.8-flash` is a quality upgrade; `gemini-3.5-flash-lite` is the cheapest/fastest and the current default.
- **Change email styling**: edit [`templates/digest.html.j2`](templates/digest.html.j2).
- **Publish the archive as a site**: the Markdown files under `digests/` are ready for GitHub Pages or any static site generator.

## Troubleshooting

- **`GEMINI_API_KEY not set`** in logs: set the secret or run with `--dry-run`.
- **`EmailConfigError`**: one of the SMTP/email secrets is missing.
- **`smtplib.SMTPAuthenticationError`**: double-check `BREVO_SMTP_LOGIN` and `BREVO_SMTP_KEY`; the SMTP key is distinct from the v3 REST API key.
- **Feed parse errors** for a single source: the workflow logs a warning and skips that source. Fix the URL in `feeds.yaml` or remove it.
- **No items in digest**: either nothing new in 48h or Gemini dropped everything as irrelevant. The run still succeeds; no email is sent but history is still saved to the cache.
- **Duplicates between consecutive runs**: the restore step probably missed. Check **Actions -> Caches** for a `history-*` entry; if empty, the previous run didn't finish the save step. Caches evict after 7 days of inactivity.
