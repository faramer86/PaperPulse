"""Rendering of a Springer Nature article record into a Telegram channel post.

Posts use HTML parse mode rather than Markdown: scientific text is full of
``_``, ``*`` and ``[`` (gene names, formulae, "[sic]"), and any unbalanced pair
makes Telegram reject the whole message. HTML only needs ``&``, ``<`` and ``>``
escaped, and :func:`html.escape` handles those exactly.

The layout is fixed by
``docs/superpowers/specs/2026-08-07-post-readability-design.md``.
"""

from datetime import date
from html import escape

from telegram import LinkPreviewOptions
from telegram.constants import MessageLimit

ELLIPSIS = '…'
# Every nature.com article page carries an og:image, so the preview always has
# a picture to show. False puts it below the text, so the title leads.
PREVIEW_ABOVE_TEXT = False


def article_url(article: dict) -> str:
    """
    Action: pick the reader-facing web link for an article
    :param article: dictionary from API response with individual article data
    :return: nature.com HTML url, or a doi.org url when only a PDF is listed
    """
    for link in article['url']:
        if link.get('format') == 'html':
            return link['value']
    return f'https://doi.org/{article["doi"]}'


def preview_for(article: dict) -> LinkPreviewOptions:
    """
    Action: build the link preview that gives a post its picture
    :param article: dictionary from API response with individual article data
    :return: preview options aimed at the article's web page

    Pinned explicitly: Telegram otherwise previews the first URL in the text,
    which is the doi.org link, and following that redirect is needless work.
    """
    return LinkPreviewOptions(url=article_url(article),
                              prefer_large_media=True,
                              show_above_text=PREVIEW_ABOVE_TEXT)


def article_type(article: dict) -> str:
    """
    Action: read the human-facing article type out of Springer's genre list
    :param article: dictionary from API response with individual article data
    :return: type such as "Review Article", or '' when the genre list is empty
    """
    genres = article.get('genre') or []
    # Springer lists a machine genre first ("ReviewPaper") and the display name
    # second ("Review Article"); prefer the one that reads like prose.
    spaced = [genre for genre in genres if ' ' in genre]
    if spaced:
        return spaced[0]
    return genres[-1] if genres else ''


def hashtags(journal_name: str, article: dict, today: date) -> str:
    """
    Action: build the hashtag line that closes a post
    :param journal_name: journal name from JID dict
    :param article: dictionary from API response with individual article data
    :param today: fallback month for records without an online date
    :return: string such as "#NatureReviewsCancer #ReviewArticle #NatureAugust2026"

    The article type lives here rather than in a header line so that it is
    tappable, which makes the channel filterable by type.
    """
    tags = [f'#{journal_name}']
    if kind := article_type(article):
        tags.append('#' + kind.replace(' ', ''))
    if article.get('openaccess') == 'true':
        tags.append('#OpenAccess')
    online = article.get('onlineDate')
    when = date.fromisoformat(online) if online else today
    tags.append(when.strftime('#Nature%B%Y'))
    return ' '.join(tags)


def _trim_to_sentence(text: str, budget: int) -> str:
    """Cut `text` to at most `budget` characters, preferring a sentence end."""
    if len(text) <= budget:
        return text
    clipped = text[:budget - len(ELLIPSIS)]
    sentence_end = max(clipped.rfind('. '), clipped.rfind('? '), clipped.rfind('! '))
    if sentence_end > budget // 3:
        return clipped[:sentence_end + 1] + ELLIPSIS
    return clipped[:clipped.rfind(' ')] + ELLIPSIS if ' ' in clipped else clipped + ELLIPSIS


def render_post(article: dict, journal_name: str, today: date) -> str:
    """
    Action: build the HTML message body for one article
    :param article: dictionary from API response with individual article data
    :param journal_name: journal name from JID dict, used for the hashtag
    :param today: fallback month for records without an online date
    :return: HTML string within Telegram's message length limit
    """
    title = f'<b>{escape(article["title"])}</b>'
    tail = (f'<b>Link:</b> https://doi.org/{escape(article["doi"])}'
            f'\n\n{escape(hashtags(journal_name, article, today))}')

    abstract = (article.get('abstract') or '').strip()
    if not abstract:
        return f'{title}\n\n{tail}'

    # Budget what is left for the abstract once the fixed parts are laid out.
    # Escaping can grow the text, so measure the escaped form against the limit.
    fixed = len(title) + len('\n\n<blockquote expandable></blockquote>\n\n') + len(tail)
    budget = MessageLimit.MAX_TEXT_LENGTH - fixed
    quoted = escape(_trim_to_sentence(abstract, budget))
    while len(quoted) > budget:
        abstract = abstract[:len(abstract) - (len(quoted) - budget) - 1]
        quoted = escape(_trim_to_sentence(abstract, budget))

    return f'{title}\n\n<blockquote expandable>{quoted}</blockquote>\n\n{tail}'
