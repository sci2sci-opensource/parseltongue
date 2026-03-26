"""Markdown parser plugins."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..markdown import Markdown


class Plugin(Protocol):
    def __call__(self, md: "Markdown") -> None: ...
