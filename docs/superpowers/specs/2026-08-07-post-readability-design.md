# Channel post format and readability

Design for how one Springer Nature article is rendered into a Telegram channel post.

## Goal

Make posts readable in a feed: scannable when skimming, complete when one stops to
read, and never a wall of text. Replace a format that showed only title, full
abstract, hashtags and a bare URL.

## What Telegram actually permits

The starting question was about fonts, sizes and alignment. None of those exist.

**Not available at any tier:** font family, font size, text colour, alignment,
line spacing, indentation. The reader's client chooses the typeface and size. The
only typeface lever is monospace via `<code>`, and everything is left-aligned.

Unicode "fake bold" (`𝐁𝐨𝐥𝐝`) and "fake sans" were considered and rejected: they are
distinct codepoints that break search, copy-paste and screen readers. For a channel
whose readers search and forward posts, that cost is not worth paying.

**Available in a standard message (4096 chars):** bold, italic, underline,
strikethrough, spoiler, monospace, `<blockquote>`, `<blockquote expandable>`, links,
link-preview control, inline keyboards, and `<tg-time>` relative timestamps.

**Available in a rich message** (`sendRichMessage`, Bot API 10.2; 32,768 chars):
headings, lists, tables, `<sub>`/`<sup>`, `<mark>`, LaTeX via `<tg-math>`, collapsible
details, and embedded media blocks. Verified working against this bot.

## Why standard messages, not rich

Rich messages were tested and adopted, then rejected on evidence:

| Claimed benefit | Measured reality |
| --- | --- |
| 32,768 chars ends truncation | 37 review abstracts sampled: median 1766, max 3218, against a ~3896 budget. **None are truncated.** |
| Superscripts, subscripts, LaTeX | Springer returns flat Unicode prose with no markup. Nothing marks which digits are subscripts, so producing them means guessing with regex. |
| Lists, tables, highlighting | Abstracts are unstructured prose. Nothing to put in them. |
| — | `sendRichMessage` has **no `link_preview_options`**. Adopting it drops the preview image. |

Named HTML entities (`&times;`, `&alpha;`) are also not decoded in rich HTML, though
that is avoidable rather than disqualifying.

Rich messages therefore cost the image and buy nothing for this data.

## Why no button

An inline URL button ("Read on nature.com") was prototyped and dropped: it adds a
fourth band of vertical weight to every post, and the `Link:` line covers
discoverability at no visual cost.

A button that *reveals* the abstract is not buildable here, for three independent
reasons:

- It requires a callback button, and this bot is a cron script with no listener.
  Nothing would answer the tap.
- In a channel, answering by editing the message changes it for **every** subscriber.
  One reader opening the abstract opens it for all of them.
- The popup alternative, `answerCallbackQuery`, caps at 200 characters against a
  median abstract of 1766.

Inline **URL** buttons remain viable for future use — they are stateless, so unlike
callback buttons they work correctly in channels.

## The format

Standard message, `parse_mode=HTML`:

```
<b>{title}</b>

<blockquote expandable>{abstract}</blockquote>

<b>Link:</b> https://doi.org/{doi}

#{Journal} #{ArticleType} #Nature{Month}{Year}
```

`#OpenAccess` is inserted after `#{ArticleType}` when the record has
`openaccess == "true"`, and omitted otherwise. An article with no abstract omits the
blockquote and its surrounding blank line entirely; every other line always appears.

Link preview: `LinkPreviewOptions(url={html_url}, prefer_large_media=True,
show_above_text=False)`. No `reply_markup`.

Decisions embedded above, each made against a rendered sample:

- **Title is bold, not a link.** The `Link:` line carries the URL instead.
- **Abstract in an expandable blockquote.** The only treatment that previews the
  opening lines *and* collapses the bulk; a spoiler hides everything, so a reader
  cannot skim to decide.
- **No journal or article-type header.** Both are redundant with the hashtags, and
  the type moves into `#ReviewArticle`, which is tappable and therefore filterable.
- **No author line.**
- **Image below the text**, so the title leads.
- **Preview pinned explicitly to the html URL.** Telegram otherwise previews the
  first URL in the text, which is now the `doi.org` link; pinning also guarantees
  the html page rather than the PDF.
- **Hashtags last.** They are metadata for search and filtering, not something a
  reader needs while reading, so they sit below the link rather than between the
  abstract and it.

## Implementation

**`post.py`**

- Rewrite `render_post` to the format above. Its signature becomes
  `render_post(article, journal_name, today)` and it builds its own hashtags,
  rather than receiving a pre-built string. That removes the need to thread tags
  through the caller.
- Move hashtag construction here from `SpringerNatureBot.hashtags` as
  `hashtags(journal_name, article, today)`; it is presentation. It gains the
  article-type slug (`Review Article` → `#ReviewArticle`) and a conditional
  `#OpenAccess`. The month still comes from the article's `onlineDate`, falling
  back to `today` when absent.
- Delete `authors_line` and `MAX_LISTED_AUTHORS`, and the journal/type header block.
  All become unreachable; remove rather than leave unused.
- Keep `article_type`, `article_url`, `preview_for` and `_trim_to_sentence`.
  `article_type` in particular is also used by `SpringerNatureBot.is_wanted` to
  filter genres, so it is not dead code.
- Recompute the length budget for the new wrapper: title, blockquote tags, hashtags
  and the link line all consume it before the abstract does.
- `PREVIEW_ABOVE_TEXT` stays `False`.

**`SpringerNatureBot.py`**

- Drop `hashtags()`; call the one in `post.py`.
- `post_new_articles` keeps `parse_mode=HTML` and `preview_for(article)`.

**Escaping** stays `html.escape`, which emits only `&amp;`, `&lt;`, `&gt;`, `&quot;`.
Named entities must never be emitted.

## Testing

Existing tests assert the author line and the journal/type header are present, so
they fail first, then pass against the new shape. New coverage:

- Title rendered bold and **not** wrapped in an anchor.
- Abstract wrapped in `<blockquote expandable>`; absent abstract produces no block.
- Hashtags contain journal, type slug and month; `#OpenAccess` appears only when
  `openaccess == 'true'`.
- Article types with spaces slug correctly (`Review Article` → `#ReviewArticle`).
- `Link:` line carries the `doi.org` URL.
- Post never exceeds 4096 characters, including with an oversized abstract.
- Truncation keeps the hashtags and the link line intact.
- HTML metacharacters in title and abstract are escaped; Markdown metacharacters
  (`_`, `*`, `[`) pass through untouched.

## Known tradeoffs

- The preview depends on the article page carrying an `og:image`. Verified present on
  29 of 29 postable articles, but it is an external dependency.
- `#OpenAccess` will effectively never appear on the review channels — 0 of 37 sampled
  review articles are open access. It still applies to Nature Genetics and Nature
  Machine Intelligence, which post all article types.
- Button `style` colours, if ever adopted, only render on Telegram builds newer than
  February 2026.
