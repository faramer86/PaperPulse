"""Tests for the link preview attached to each post.

Every nature.com article page carries an og:image, so the preview is what puts
a picture on the post. It is pointed at the article URL explicitly rather than
left to Telegram's "first link in the text" rule.
"""

from post import preview_for

ARTICLE = {
    'doi': '10.1038/s41568-025-00123-4',
    'url': [{'format': 'pdf', 'value': 'https://www.nature.com/articles/x.pdf'},
            {'format': 'html', 'value': 'https://www.nature.com/articles/x'}],
}


def test_preview_is_enabled():
    assert preview_for(ARTICLE).is_disabled is not True


def test_preview_points_at_the_html_article_not_the_pdf():
    """A PDF link previews as a file, not as the article's figure."""
    assert preview_for(ARTICLE).url == 'https://www.nature.com/articles/x'


def test_preview_asks_for_the_large_image():
    assert preview_for(ARTICLE).prefer_large_media is True


def test_preview_falls_back_to_doi_when_no_html_url_exists():
    article = ARTICLE | {'url': [{'format': 'pdf', 'value': 'https://x/y.pdf'}]}

    assert preview_for(article).url == 'https://doi.org/10.1038/s41568-025-00123-4'


def test_preview_placement_is_a_single_switch():
    """Whether the image leads or trails is the one aesthetic knob here."""
    import post

    assert preview_for(ARTICLE).show_above_text is post.PREVIEW_ABOVE_TEXT
