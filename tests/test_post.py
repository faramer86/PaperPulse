"""Tests for rendering one Springer article record into a channel post.

Format is fixed by docs/superpowers/specs/2026-08-07-post-readability-design.md:
bold unlinked title, expandable abstract, Link line, hashtags last.
"""

from datetime import date

import pytest
from telegram.constants import MessageLimit

from post import article_url, hashtags, render_post

TODAY = date(2026, 8, 7)

ARTICLE = {
    'title': 'Targeting the tumour microenvironment in pancreatic cancer',
    'abstract': 'Immune checkpoint blockade has transformed the treatment of many '
                'solid tumours. Pancreatic ductal adenocarcinoma remains refractory. '
                'Here we review the desmoplastic stroma.',
    'creators': [{'creator': 'Smith, Jane'}, {'creator': 'Patel, Anil'}],
    'publicationName': 'Nature Reviews Cancer',
    'genre': ['ReviewPaper', 'Review Article'],
    'doi': '10.1038/s41568-025-00123-4',
    'openaccess': 'false',
    'onlineDate': '2026-08-05',
    # Deliberately pdf-first: the old code took url[0] and posted PDF links.
    'url': [{'format': 'pdf', 'value': 'https://www.nature.com/articles/x.pdf'},
            {'format': 'html', 'value': 'https://www.nature.com/articles/x'}],
}

JOURNAL = 'NatureReviewsCancer'


def render(article=None, journal=JOURNAL):
    return render_post(article or ARTICLE, journal, TODAY)


def test_links_to_the_html_version_not_the_pdf():
    assert article_url(ARTICLE) == 'https://www.nature.com/articles/x'


def test_falls_back_to_doi_when_no_html_url_is_listed():
    article = ARTICLE | {'url': [{'format': 'pdf', 'value': 'https://x/y.pdf'}]}

    assert article_url(article) == 'https://doi.org/10.1038/s41568-025-00123-4'


def test_title_is_bold_and_not_a_link():
    """The Link line carries the URL, so the title is plain bold."""
    post = render()

    assert post.startswith('<b>Targeting the tumour microenvironment in pancreatic cancer</b>')
    assert '<a href' not in post


def test_abstract_sits_in_an_expandable_quote():
    post = render()

    assert '<blockquote expandable>Immune checkpoint blockade' in post
    assert '</blockquote>' in post


def test_link_line_carries_the_doi():
    post = render()

    assert '<b>Link:</b> https://doi.org/10.1038/s41568-025-00123-4' in post


def test_hashtags_come_last():
    post = render()

    assert post.rstrip().endswith('#NatureReviewsCancer #ReviewArticle #NatureAugust2026')
    assert post.index('<b>Link:</b>') < post.index('#NatureReviewsCancer')


def test_dropped_elements_are_really_gone():
    """Journal name, article-type header and authors were all removed."""
    post = render()

    assert 'Nature Reviews Cancer' not in post
    assert 'Smith' not in post
    assert 'Patel' not in post


def test_article_type_becomes_a_tappable_slug():
    assert '#ReviewArticle' in hashtags(JOURNAL, ARTICLE, TODAY)
    assert '#Perspective' in hashtags(JOURNAL, ARTICLE | {'genre': ['Perspective']}, TODAY)


def test_open_access_is_tagged_only_when_true():
    assert '#OpenAccess' not in hashtags(JOURNAL, ARTICLE, TODAY)
    assert '#OpenAccess' in hashtags(JOURNAL, ARTICLE | {'openaccess': 'true'}, TODAY)


def test_month_comes_from_the_article_not_from_today():
    tags = hashtags(JOURNAL, ARTICLE | {'onlineDate': '2026-07-30'}, TODAY)

    assert '#NatureJuly2026' in tags


def test_month_falls_back_to_today_without_an_online_date():
    article = {key: value for key, value in ARTICLE.items() if key != 'onlineDate'}

    assert '#NatureAugust2026' in hashtags(JOURNAL, article, TODAY)


def test_html_metacharacters_in_scientific_text_are_escaped():
    article = ARTICLE | {'title': 'Effect of p < 0.05 & CD8+ <T> cells'}

    post = render(article)

    assert '&lt;T&gt;' in post
    assert 'p &lt; 0.05 &amp; CD8+' in post


def test_markdown_metacharacters_pass_through_untouched():
    article = ARTICLE | {'title': 'BRCA1_v2 and 5*10^6 cells [sic]'}

    assert 'BRCA1_v2 and 5*10^6 cells [sic]' in render(article)


@pytest.mark.parametrize('repeats', [0, 500, 6000, 40000])
def test_post_never_exceeds_the_telegram_limit(repeats):
    article = ARTICLE | {'abstract': 'Sentence about tumours. ' * repeats}

    assert len(render(article)) <= MessageLimit.MAX_TEXT_LENGTH


def test_truncation_keeps_the_link_and_the_hashtags():
    article = ARTICLE | {'abstract': 'Long sentence about tumours. ' * 1000}

    post = render(article)

    assert 'https://doi.org/10.1038/s41568-025-00123-4' in post
    assert '#NatureReviewsCancer' in post
    assert len(post) <= MessageLimit.MAX_TEXT_LENGTH


def test_oversized_abstract_is_trimmed_at_a_sentence_boundary():
    article = ARTICLE | {'abstract': 'A tumour sentence here. ' * 1000}

    quoted = render(article).split('<blockquote expandable>')[1].split('</blockquote>')[0]

    assert quoted.rstrip('…').rstrip().endswith('.')


def test_article_without_abstract_renders_without_a_quote_block():
    post = render(ARTICLE | {'abstract': ''})

    assert '<blockquote' not in post
    assert post.startswith('<b>Targeting')
    assert '<b>Link:</b>' in post


@pytest.mark.parametrize('genre, expected', [
    ('Review Article', '#ReviewArticle'),
    ('Perspective', '#Perspective'),
    # Telegram hashtags accept only letters, digits and underscore, so a bare
    # "&" silently ends the tag: "#News&Views" becomes the tag "#News".
    ('News & Views', '#NewsAndViews'),
    ('News And Views', '#NewsAndViews'),
    ('Career Q&A', '#CareerQAndA'),
    ('Tools of the Trade', '#ToolsoftheTrade'),
    ('Research Briefings', '#ResearchBriefings'),
])
def test_article_type_slugs_are_valid_hashtags(genre, expected):
    tags = hashtags(JOURNAL, ARTICLE | {'genre': [genre]}, TODAY)

    assert expected in tags


def test_the_two_spellings_of_news_and_views_produce_one_tag():
    """Springer returns both 'News & Views' and 'News And Views'."""
    ampersand = hashtags(JOURNAL, ARTICLE | {'genre': ['News & Views']}, TODAY)
    spelled = hashtags(JOURNAL, ARTICLE | {'genre': ['News And Views']}, TODAY)

    assert ampersand == spelled


def test_no_hashtag_ever_contains_a_character_telegram_would_cut():
    for genre in ('News & Views', 'Career Q&A', 'Tools of the Trade',
                  'Review Article', 'Editorial Expression of Concern'):
        tags = hashtags(JOURNAL, ARTICLE | {'genre': [genre]}, TODAY)
        for tag in tags.split():
            assert tag.startswith('#')
            assert tag[1:].replace('_', '').isalnum(), tag
