from app.utils.text import html_to_text


def test_strips_tags_and_keeps_paragraphs() -> None:
    html = (
        "<h2>About us</h2><p>We   build <b>things</b>.</p><ul><li>Python</li><li>Django</li></ul>"
    )

    text = html_to_text(html)

    assert "<" not in text
    assert "About us" in text
    assert "We build" in text
    assert "Python\n" in text or "Python" in text.splitlines()


def test_collapses_blank_lines_and_spaces() -> None:
    html = "<p>One</p>\n\n\n<p>&nbsp;&nbsp;Two   words</p><br><br><br><p>Three</p>"

    text = html_to_text(html)

    assert "\n\n\n" not in text
    assert "Two words" in text
    assert text.startswith("One")
    assert text.endswith("Three")


def test_drops_scripts_and_styles() -> None:
    assert html_to_text("<style>p{}</style><script>alert(1)</script><p>Hi</p>") == "Hi"
