from rag_mcp.loading.html_text import html_to_text


def test_html_to_text_keeps_blocks_drops_scripts_and_decodes_entities() -> None:
    html = """<html><head><title>T &amp; U</title><style>p{}</style></head>
    <body><nav>menu</nav><h1>Head</h1><p>one &lt;two&gt;</p><ul><li>a</li><li>b</li></ul>
    <script>alert(1)</script><pre>code
  block</pre></body></html>"""
    page = html_to_text(html)
    assert page.title == "T & U"
    assert page.text.split("\n\n") == ["Head", "one <two>", "a", "b", "code\n  block"]


def test_html_to_text_handles_empty_and_unclosed_markup() -> None:
    assert html_to_text("") == html_to_text("<div><p>")
    assert html_to_text("<p>only").text == "only"
