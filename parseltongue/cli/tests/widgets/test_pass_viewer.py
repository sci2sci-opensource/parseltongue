"""Tests for pass_viewer highlighting — reproducing bracket/markup issues."""

import re

import pytest
from textual.markup import to_content

from parseltongue.cli.tui.widgets.pass_viewer import _highlight, _safe_highlight, pv_escape

# --- Basic highlighting ---


class TestHighlightScheme:
    def test_simple_sexp(self):
        src = '(define x 42)'
        result = _highlight(src, "scheme")
        assert result
        to_content(result)

    def test_nested_sexp(self):
        src = '(if (> x 0) (+ x 1) (- x 1))'
        result = _highlight(src, "scheme")
        to_content(result)

    def test_string_with_brackets(self):
        src = '(define msg "value is [42]")'
        result = _highlight(src, "scheme")
        to_content(result)

    def test_ref_link_no_patterns_in_scheme(self):
        """Scheme has no patterns — refs are not clickable."""
        src = '[[fact:auth-check]]'
        result = _highlight(src, "scheme")
        assert "ref_clicked" not in result
        to_content(result)


class TestHighlightMarkdown:
    def test_plain_text(self):
        src = "Hello world"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_heading(self):
        src = "# Title\n\nSome text."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_link(self):
        src = "See [this link](http://example.com) for details."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_square_brackets_in_text(self):
        """The [ Berlin ] case — brackets in natural language."""
        src = "The city [ Berlin ] is the capital of Germany."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_multiple_brackets(self):
        src = "Options: [a] first, [b] second, [c] third."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_nested_brackets(self):
        src = "See [[nested]] and [single] brackets."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_markdown_image(self):
        src = "![alt text](image.png)"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_markdown_checkbox(self):
        src = "- [x] Done\n- [ ] Todo"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_code_fence_with_brackets(self):
        src = '```python\ndata = {"key": [1, 2, 3]}\n```'
        result = _highlight(src, "markdown")
        to_content(result)

    def test_bold_italic_combo(self):
        src = "This is **bold** and *italic* and ***both***."
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_standalone_bracket(self):
        """Standalone '[' inside italic span."""
        src = "> text with [ standalone bracket\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_bracket_pair(self):
        """Italic content with [something] inside."""
        src = "> check [Berlin] and [Munich] data\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_bold_with_bracket(self):
        src = "**bold [text] here**"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_unmatched_open_bracket(self):
        """'[' that textual_escape doesn't escape."""
        src = "> array = [1, 2, 3\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_trailing_open_bracket(self):
        """Standalone '[' at end of italic span."""
        src = "> see section [\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_open_bracket_then_close_tag(self):
        """'[' inside italic swallows the [/italic] closer."""
        src = "> text [ more text\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_empty_brackets(self):
        src = "> value is [] empty\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_valid_tag_name(self):
        """Source text [b] or [i] opens a real Textual tag inside italic."""
        src = "> option [b] is correct\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_italic_with_style_names(self):
        """Various valid Textual style names in source text."""
        for tag in ["b", "i", "u", "bold", "italic", "red", "green", "dim"]:
            src = f"> text [{tag}] more\n"
            result = _highlight(src, "markdown")
            to_content(result)

    def test_emph_with_slash_tag(self):
        """Source containing [/something] inside emphasis."""
        cases = [
            "> text [/] end",
            "> use [/italic] to close",
            "> see [/bold] tag",
            "> code: [/b]",
            "*text [/italic] here*",
            "> a]b",
            "> a[b",
            "> a[b]c[d",
            " **[●]** ",
        ]
        for src in cases:
            result = _highlight(src + "\n", "markdown")
            to_content(result)

    def test_no_unescaped_brackets_in_styled_spans(self):
        """No raw [ or ] must appear inside [style]...[/style] blocks."""
        tag_re = re.compile(r'\[([a-z ]+)\](.*?)\[/\1\]', re.DOTALL)

        sources = [
            "> quote with [brackets]\n",
            "> text [bold more words\n",
            "> see [red stuff here\n",
            "> data [on and on\n",
            "*emphasis [link](url)*\n",
            "> a[b\n",
            "> a[b]c[d\n",
            "> value is [] empty\n",
            "> text [/italic] here\n",
            "> option [b] is correct\n",
            "**bold [text] here**\n",
            "> check [Berlin] and [Munich] data\n",
            "> array = [1, 2, 3\n",
            "[ *Berlin* ] registered\n",
            "[ *Charlottenburg* ] in [ *Berlin* ] under [ *HRB 265413 B* ]\n",
            '(the " **Borrower** ")\n',
            "under [ *Berlin* under [ *HRB 123* ]\n",
        ]
        for src in sources:
            markup = _highlight(src, "markdown")
            for m in tag_re.finditer(markup):
                style, content = m.group(1), m.group(2)
                unescaped_open = re.findall(r'(?<!\\)\[', content)
                unescaped_close = re.findall(r'(?<!\\)\]', content)
                assert not unescaped_open, f"Unescaped '[' in [{style}] span for {src!r}: content={content!r}"
                assert not unescaped_close, f"Unescaped ']' in [{style}] span for {src!r}: content={content!r}"

    def test_table(self):
        src = "| Name | City |\n|------|------|\n| Alice | [Berlin] |"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_footnote_style_refs(self):
        src = "Some claim [1] and another [2].\n\n[1]: http://example.com\n[2]: http://other.com"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_blockquote_with_brackets(self):
        src = '> The report states: "GDP of [Germany] rose by 2%."'
        result = _highlight(src, "markdown")
        to_content(result)

    def test_legal_clause_nested_brackets_and_emphasis(self):
        """Real legal contract pattern: nested brackets with italic inside."""
        src = (
            "**** , with its seat in [ *Berlin* ], registered with the "
            "commercial register at the local court of [ *Charlottenburg* ] "
            "in [ *Berlin* ] under [ *HRB 265413 B* ]\n\n"
            '(the " **Borrower** ")\n'
        )
        result = _highlight(src, "markdown")
        to_content(result)

    def test_bracket_with_italic_inside(self):
        """Bracket containing italic text — [ *word* ]."""
        src = "See [ *Berlin* ] for details.\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_multiple_bracket_italic_spans(self):
        """Multiple [ *italic* ] spans in one line."""
        src = "Filed in [ *Munich* ] and [ *Frankfurt* ] courts.\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_nested_bracket_missing_close(self):
        """Unclosed outer bracket with inner [ *italic* ] bracket."""
        src = "under [ *Berlin* under [ *HRB 123* ]\n"
        result = _highlight(src, "markdown")
        to_content(result)

    def test_bold_in_quotes_after_brackets(self):
        """Bold text in quotes following bracket sequences."""
        src = '[ *Berlin* ] (the " **Borrower** ")\n'
        result = _highlight(src, "markdown")
        to_content(result)

    def test_long_document_mixed(self):
        """Realistic document excerpt with mixed markdown features."""
        src = """# Analysis Report

## Key Findings

The data from [Berlin] and [Munich] shows:

1. **Population**: [Berlin] has ~3.7M residents
2. **GDP**: See table below

| City | Pop (M) | GDP (B€) |
|------|---------|----------|
| [Berlin] | 3.7 | 155 |
| [Munich] | 1.5 | 122 |

> Note: Values are approximate [source: Federal Statistics Office]

### References

- [1] Federal Statistics Office, 2024
- [2] World Bank Data [online]
"""
        result = _highlight(src, "markdown")
        to_content(result)

    def test_emph_tokens_from_blockquotes(self):
        """Blockquotes produce Token.Generic.Emph — verify they contain brackets."""
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token

        lexer = get_lexer_by_name("markdown")

        src = "> quote with [brackets]"
        emph_tokens = [(t, v) for t, v in lex(src, lexer) if t in Token.Generic.Emph]
        assert emph_tokens, "Blockquote should produce Generic.Emph tokens"

    def test_full_markdown_highlight_succeeds(self):
        """Full markdown document highlights without fallback."""
        src = """\
# Report Title

Some **bold** text and *italic* text.

A paragraph with [a link](http://example.com) and ![an image](pic.png).

## List

- Item one
- Item [two] with brackets
- [x] checkbox done

> A blockquote with [Berlin] reference

| Col A | Col B |
|-------|-------|
| hello | [world] |

Footnotes: see [1] and [2].

[1]: http://one.com
[2]: http://two.com

```python
x = [1, 2, 3]
```
"""
        result = _safe_highlight(src, "markdown")
        assert "highlight unavailable" not in result


# --- Safe highlight fallback ---


class TestSafeHighlight:
    def test_returns_markup_on_success(self):
        result = _safe_highlight("(define x 1)", "scheme")
        assert "highlight unavailable" not in result

    def test_fallback_on_broken_markup(self):
        """If _highlight somehow produces bad markup, _safe_highlight catches it."""
        result = _safe_highlight("[ Berlin ] test", "markdown")
        assert isinstance(result, str)
        assert len(result) > 0


# --- Escape correctness ---


class TestEscapeInteraction:
    """Verify textual_escape handles all bracket patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "[Berlin]",
            "[ Berlin ]",
            "[[nested]]",
            "[link](url)",
            "[x] checkbox",
            "a [b] c [d] e",
            "[bold]not a tag[/bold]",
            "[red]fake tag[/red]",
            "\\[escaped\\]",
        ],
    )
    def test_escape_then_parse(self, text):
        escaped = pv_escape(text)
        to_content(escaped)

    @pytest.mark.parametrize(
        "text",
        [
            "[Berlin]",
            "[ Berlin ]",
            "[link](url)",
            "[bold]not a tag[/bold]",
            "]bare closing bracket",
            "text]in]middle",
        ],
    )
    def test_escape_in_color_tag(self, text):
        """Escaped text wrapped in color tags must still be valid."""
        escaped = pv_escape(text)
        markup = f"[yellow]{escaped}[/yellow]"
        to_content(markup)
