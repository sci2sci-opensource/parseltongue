"""Unit tests for pass_viewer pattern classes — exact output assertions."""

from pygments.token import Token

from parseltongue.cli.tui.widgets.pass_viewer import (
    _LANGUAGE_SPECS,
    InlineRefPattern,
    LexemPattern,
    RefPattern,
    TokenSlot,
    _highlight,
)

# ---------------------------------------------------------------------------
# TokenSlot
# ---------------------------------------------------------------------------


class TestTokenSlot:
    def test_exact_match(self):
        slot = TokenSlot(Token.Text, "[")
        assert slot.matches(Token.Text, "[") is True

    def test_wrong_value(self):
        slot = TokenSlot(Token.Text, "[")
        assert slot.matches(Token.Text, "]") is False

    def test_wrong_type(self):
        slot = TokenSlot(Token.Text, "[")
        assert slot.matches(Token.Name, "[") is False

    def test_any_value(self):
        slot = TokenSlot(Token.Name.Tag)
        assert slot.matches(Token.Name.Tag, "anything") is True
        assert slot.matches(Token.Name.Tag, "") is True

    def test_any_value_wrong_type(self):
        slot = TokenSlot(Token.Name.Tag)
        assert slot.matches(Token.Text, "anything") is False

    def test_any_type_and_value(self):
        slot = TokenSlot()
        assert slot.matches(Token.Text, "x") is True
        assert slot.matches(Token.Name.Attribute, "http://foo") is True

    def test_any_type_specific_value(self):
        slot = TokenSlot(value="[")
        assert slot.matches(Token.Text, "[") is True
        assert slot.matches(Token.Punctuation, "[") is True
        assert slot.matches(Token.Text, "]") is False


# ---------------------------------------------------------------------------
# LexemPattern.try_match
# ---------------------------------------------------------------------------


class TestLexemPatternMatch:
    TOKENS = [
        (Token.Text, "["),
        (Token.Name.Tag, "link"),
        (Token.Text, "]"),
        (Token.Text, "("),
        (Token.Name.Attribute, "http://example.com"),
        (Token.Text, ")"),
    ]

    LINK_PATTERN = LexemPattern(
        slots=[
            TokenSlot(Token.Text, "["),
            TokenSlot(Token.Name.Tag),
            TokenSlot(Token.Text, "]"),
            TokenSlot(Token.Text, "("),
            TokenSlot(Token.Name.Attribute),
            TokenSlot(Token.Text, ")"),
        ],
        color="cyan",
    )

    def test_full_match(self):
        assert self.LINK_PATTERN.try_match(self.TOKENS, 0) == 6

    def test_no_match_wrong_position(self):
        assert self.LINK_PATTERN.try_match(self.TOKENS, 1) == 0

    def test_no_match_not_enough_tokens(self):
        assert self.LINK_PATTERN.try_match(self.TOKENS, 3) == 0

    def test_no_match_wrong_type(self):
        bad_tokens = [(Token.Name, "[")] + list(self.TOKENS[1:])
        assert self.LINK_PATTERN.try_match(bad_tokens, 0) == 0

    def test_no_match_wrong_value(self):
        bad_tokens = [(Token.Text, "!")] + list(self.TOKENS[1:])
        assert self.LINK_PATTERN.try_match(bad_tokens, 0) == 0

    def test_empty_token_list(self):
        assert self.LINK_PATTERN.try_match([], 0) == 0


# ---------------------------------------------------------------------------
# LexemPattern.render
# ---------------------------------------------------------------------------


class TestLexemPatternRender:
    def test_link_render(self):
        tokens = [
            (Token.Text, "["),
            (Token.Name.Tag, "link"),
            (Token.Text, "]"),
            (Token.Text, "("),
            (Token.Name.Attribute, "http://ex.com"),
            (Token.Text, ")"),
        ]
        pattern = LexemPattern(
            slots=[
                TokenSlot(Token.Text, "["),
                TokenSlot(Token.Name.Tag),
                TokenSlot(Token.Text, "]"),
                TokenSlot(Token.Text, "("),
                TokenSlot(Token.Name.Attribute),
                TokenSlot(Token.Text, ")"),
            ],
            color="cyan",
        )
        result = pattern.render(tokens, 0, 6)
        assert result == "[cyan]\\[link\\](http://ex.com)[/cyan]"

    def test_render_no_color(self):
        tokens = [(Token.Text, "hello")]
        pattern = LexemPattern(slots=[TokenSlot(Token.Text)], color=None)
        result = pattern.render(tokens, 0, 1)
        assert result == "hello"

    def test_render_brackets_escaped_in_color(self):
        tokens = [(Token.Text, "[x]")]
        pattern = LexemPattern(slots=[TokenSlot(Token.Text)], color="red")
        result = pattern.render(tokens, 0, 1)
        assert result == "[red]\\[x\\][/red]"


# ---------------------------------------------------------------------------
# RefPattern
# ---------------------------------------------------------------------------


class TestRefPattern:
    REF = RefPattern()

    def test_match_single_token(self):
        tokens = [(Token.Text, "[[fact:check]]")]
        assert self.REF.try_match(tokens, 0) == 1

    def test_match_multi_token(self):
        tokens = [
            (Token.Punctuation, "[["),
            (Token.Text, "fact:check"),
            (Token.Punctuation, "]]"),
        ]
        assert self.REF.try_match(tokens, 0) == 3

    def test_no_match_no_bracket(self):
        tokens = [(Token.Text, "hello")]
        assert self.REF.try_match(tokens, 0) == 0

    def test_no_match_single_bracket(self):
        tokens = [(Token.Text, "[not a ref]")]
        assert self.REF.try_match(tokens, 0) == 0

    def test_render_single_token(self):
        tokens = [(Token.Text, "[[fact:check]]")]
        result = self.REF.render(tokens, 0, 1)
        assert result == ("[@click=screen.ref_clicked('fact','check')]" "[bold cyan]check[/bold cyan]" "[/]")

    def test_render_multi_token(self):
        tokens = [
            (Token.Punctuation, "[["),
            (Token.Text, "fact:auth"),
            (Token.Punctuation, "]]"),
        ]
        result = self.REF.render(tokens, 0, 3)
        assert result == ("[@click=screen.ref_clicked('fact','auth')]" "[bold cyan]auth[/bold cyan]" "[/]")


# ---------------------------------------------------------------------------
# InlineRefPattern
# ---------------------------------------------------------------------------


class TestInlineRefPattern:
    INLINE = InlineRefPattern()

    def test_match_token_with_ref(self):
        tokens = [(Token.Text, "see [[fact:x]] here")]
        assert self.INLINE.try_match(tokens, 0) == 1

    def test_no_match_no_ref(self):
        tokens = [(Token.Text, "plain text")]
        assert self.INLINE.try_match(tokens, 0) == 0

    def test_render_ref_with_surrounding_text(self):
        tokens = [(Token.Text, "see [[fact:x]] here")]
        result = self.INLINE.render(tokens, 0, 1)
        assert result == ("see " "[@click=screen.ref_clicked('fact','x')]" "[bold cyan]x[/bold cyan]" "[/]" " here")

    def test_render_multiple_refs_in_token(self):
        tokens = [(Token.Text, "[[a:b]] and [[c:d]]")]
        result = self.INLINE.render(tokens, 0, 1)
        assert result == (
            "[@click=screen.ref_clicked('a','b')]"
            "[bold cyan]b[/bold cyan]"
            "[/]"
            " and "
            "[@click=screen.ref_clicked('c','d')]"
            "[bold cyan]d[/bold cyan]"
            "[/]"
        )

    def test_render_ref_at_start(self):
        tokens = [(Token.Text, "[[fact:x]] end")]
        result = self.INLINE.render(tokens, 0, 1)
        assert result == ("[@click=screen.ref_clicked('fact','x')]" "[bold cyan]x[/bold cyan]" "[/]" " end")

    def test_render_ref_at_end(self):
        tokens = [(Token.Text, "start [[fact:x]]")]
        result = self.INLINE.render(tokens, 0, 1)
        assert result == ("start " "[@click=screen.ref_clicked('fact','x')]" "[bold cyan]x[/bold cyan]" "[/]")


# ---------------------------------------------------------------------------
# _highlight — scheme produces no pattern output
# ---------------------------------------------------------------------------


class TestHighlightScheme:
    def test_no_ref_detection(self):
        result = _highlight("[[fact:check]]", "scheme")
        assert "ref_clicked" not in result

    def test_no_link_detection(self):
        result = _highlight('"[link](http://example.com)"', "scheme")
        assert "cyan" not in result or "ref_clicked" not in result


# ---------------------------------------------------------------------------
# _highlight — markdown patterns produce expected output
# ---------------------------------------------------------------------------


class TestHighlightMarkdownPatterns:
    def test_ref_clickable(self):
        result = _highlight("[[fact:check]]", "markdown")
        assert "[@click=screen.ref_clicked('fact','check')]" in result
        assert "[bold cyan]check[/bold cyan]" in result

    def test_link_cyan(self):
        result = _highlight("[link](http://ex.com)", "markdown")
        assert "[cyan]" in result
        assert "[/cyan]" in result
        assert "ref_clicked" not in result

    def test_image_dim_cyan(self):
        result = _highlight("![alt](pic.png)", "markdown")
        assert "[dim cyan]" in result
        assert "[/dim cyan]" in result

    def test_link_not_confused_with_ref(self):
        result = _highlight("[text](url)", "markdown")
        assert "ref_clicked" not in result

    def test_ref_not_confused_with_link(self):
        result = _highlight("[[fact:x]]", "markdown")
        assert "ref_clicked" in result
        assert "cyan" in result  # bold cyan from ref rendering


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_only_markdown_has_spec(self):
        assert set(_LANGUAGE_SPECS.keys()) == {"markdown"}

    def test_markdown_pattern_order(self):
        """RefPattern before LexemPatterns before InlineRefPattern."""
        patterns = _LANGUAGE_SPECS["markdown"].patterns
        ref_idx = next(i for i, p in enumerate(patterns) if isinstance(p, RefPattern))
        inline_idx = next(i for i, p in enumerate(patterns) if isinstance(p, InlineRefPattern))
        slot_indices = [i for i, p in enumerate(patterns) if type(p) is LexemPattern]
        assert ref_idx < min(slot_indices)
        assert inline_idx > max(slot_indices)
