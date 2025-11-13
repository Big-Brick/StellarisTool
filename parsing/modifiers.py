import re

from typing import Iterator, Type, TypeVar

from .types import BlockBase, Job, ModifierBlock, TriggeredCountryModifierBlock, TriggeredPlanetModifierBlock

from .parsing import _find_matching_brace

TBlock = TypeVar("TBlock", bound=BlockBase)

def _iter_blocks_of_type(text: str, block_cls: Type[TBlock]) -> Iterator[TBlock]:
	"""
	Generic version of _extract_block that returns typed block objects.

	It looks for:
	    <block_cls.keyword()> = { ... }

	and yields instances of block_cls with:
	    body     = inner text between '{' and '}'
	    raw_text = full text slice "keyword = { ... }"
	"""
	key = block_cls.keyword()
	pat = re.compile(r'\b' + re.escape(key) + r'\s*=\s*{')

	for m in pat.finditer(text):
		open_brace = text.find('{', m.end() - 1)
		if open_brace < 0:
			continue

		close_brace = _find_matching_brace(text, open_brace)
		if close_brace < 0:
			continue

		raw = text[m.start():close_brace + 1]
		body = text[open_brace + 1:close_brace]
		yield block_cls(body=body, raw_text=raw)


# Convenience wrappers (so call sites stay readable)
def _iter_modifier_blocks(text: str) -> Iterator[ModifierBlock]:
	return _iter_blocks_of_type(text, ModifierBlock)


def _iter_triggered_country_modifier_blocks(text: str) -> Iterator[TriggeredCountryModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredCountryModifierBlock)


def _iter_triggered_planet_modifier_blocks(text: str) -> Iterator[TriggeredPlanetModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredPlanetModifierBlock)
