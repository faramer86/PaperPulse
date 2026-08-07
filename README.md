# NatureSpringerBot

A Telegram bot that watches the Springer Nature API for new articles and posts
them to topic-specific channels.

**NOTE:** we do not download pdf versions of articles, we simply send inform
messages with title, abstract and web link to official web version of the
article. Thus, we believe, we do not violate any laws.

## Channels

Five channels, fed from 24 journals. Two carry every article type; the rest are
filtered to reviews and perspectives.

| Channel | Covers |
| --- | --- |
| [@NatureGenetics](https://t.me/NatureGenetics) | Nature Genetics — all article types |
| [@NatureMachineIntelligence](https://t.me/NatureMachineIntelligence) | Nature Machine Intelligence — all article types |
| [@NatureReviewsLife](https://t.me/NatureReviewsLife) | Life Sciences reviews and perspectives |
| [@NatureReviewsClinical](https://t.me/NatureReviewsClinical) | Clinical Sciences reviews and perspectives |
| [@NatureReviewsPhysical](https://t.me/NatureReviewsPhysical) | Physical Sciences reviews and perspectives |

**Life Sciences** — Nature, Nature Reviews Cancer, Drug Discovery, Genetics,
Immunology, Microbiology, Molecular Cell Biology, Neuroscience.

**Clinical Sciences** — Nature Reviews Cardiology, Clinical Oncology, Disease
Primers, Endocrinology, Gastroenterology & Hepatology, Nephrology, Neurology,
Rheumatology, Urology.

**Physical Sciences** — Nature Reviews Chemistry, Earth & Environment, Materials,
Physics, Methods Primers.

## What a post looks like

```
<b>{title}</b>

<blockquote expandable>{abstract}</blockquote>

<b>Link:</b> https://doi.org/{doi}

#{Journal} #{ArticleType} #Nature{Month}{Year}
```

The article image arrives as a link preview below the text. The abstract is
collapsed to a few lines with a "show more" affordance, so a busy day stays
skimmable. HTML parse mode, not Markdown — scientific text is full of `_`, `*`
and `[`, and an unbalanced pair makes Telegram reject the whole message.

The reasoning behind each choice, and the measurements it rests on, is recorded
in `docs/superpowers/specs/2026-08-07-post-readability-design.md` (kept locally,
not tracked).

## How it runs

The bot registers no update handlers — it only ever sends — so it runs as a cron
job rather than a long-lived process. One invocation queries a rolling 7-day
window per journal, posts what it has not posted before, and exits.

```bash
python SpringerNatureBot.py                 # one pass
python SpringerNatureBot.py --seed          # record the window without posting
python SpringerNatureBot.py --limit 1       # tighter pacing for this run
```

`.github/workflows/post.yml` runs it every 3 hours. Each run posts at most
`--limit` articles per channel (default 3), so a busy publication day spreads
over the following runs instead of arriving as one wall of messages.

**Run `--seed` once before the first real run**, unless you want the current
week's backlog posted. Without it the bot treats the whole window as new.

### Configuration

`config.py` is gitignored and holds `SPRINGER_API_KEY`, `BOT_API_KEY` and
`USER_CHAT_ID`. CI recreates it from repository secrets of the same names, so
there is one config mechanism rather than two code paths.

Both secrets travel inside request URLs that httpx logs at INFO — the Springer
key as a query parameter, the Telegram token as a path segment. A logging filter
scrubs both before anything is written, so neither reaches CI logs.

### Deduplication

`seen.json` maps each posted DOI to the date it went out, and the workflow
commits it back to the repo. Entries are pruned after 30 days: an article older
than the query window can never be returned again, so the file stays a few
kilobytes. Swap the backend by implementing `store.SeenStore`.

This is what removed the old two-day publication delay. That delay existed only
because the bot had no memory and had to wait for Springer's index to settle;
with dedup the window can be re-queried freely, and articles post as soon as
they are indexed.

### API budget

The Springer basic plan allows **500 requests/day** and **100/minute**. One sweep
of all 24 journals costs about 27 requests (23 journals answer in a single page;
`Nature` needs four). Run frequency, not article volume, is what spends the quota:

| cadence | runs/day | requests/day | vs 500/day |
| --- | --- | --- | --- |
| every 30 min | 48 | 1296 | over |
| hourly | 24 | 648 | over |
| every 2 h | 12 | 324 | ok |
| **every 3 h** | **8** | **216** | **ok** |

A run that exhausts its retries stops the sweep rather than continuing, because a
throttled account fails the remaining journals too and each costs three more
requests. Without that guard a throttled run would cost ~81 requests instead of
27, and eight of those would exceed the daily cap on their own.

Note that `articletype:` and `sort:date` are premium-only constraints and return
HTTP 403 on the basic plan, so article types are filtered client-side against the
`genre` field every record carries.

### Tests

```bash
pip install -r requirements.txt pytest pytest-asyncio
pytest -q
```

The suite makes no network calls — every test runs through `httpx.MockTransport`
— and stubs `config.py` when it is absent, so it passes on a fresh clone.
