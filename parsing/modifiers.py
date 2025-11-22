import re

from typing import Iterator, List, Type, TypeVar

from .context import GlobalContext, Job, Resource
from .parsing import _find_matching_brace
from .types import (
	BlockBase,
	ModifierBlock,
	JobModifierBlock,
	TriggeredCountryModifierBlock,
	TriggeredPlanetModifierBlock,
	JobEffect,
	JobEffectProductionAdd,
	JobEffectUpkeepMult)

from .parsing_job_effect import JobEffectParser

TBlock = TypeVar("TBlock", bound=BlockBase)

def _iter_blocks_of_type(text: str, block_cls: Type[TBlock]) -> Iterator[TBlock]:
	"""
	Generic version of _extract_block that returns typed block objects.

	It looks for:
		<block_cls.keyword()> = { ... }

	and yields instances of block_cls with:
		body	 = inner text between '{' and '}'
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

def split_modifier_entries(body: str) -> list[str]:
	"""
	Split a modifier body's text into top‑level entries.  Each entry ends at
	a newline when the current brace depth returns to zero, so nested blocks
	like 'key = { ... }' remain intact.
	"""
	entries: list[str] = []
	current: list[str] = []
	depth = 0
	for ch in body:
		if ch == '{':
			depth += 1
			current.append(ch)
		elif ch == '}':
			depth -= 1
			current.append(ch)
		elif ch == '\n':
			if depth == 0:
				entry = ''.join(current).strip()
				if entry:
					entries.append(entry)
				current = []
			else:
				current.append(ch)
		else:
			current.append(ch)
	# flush last entry
	entry = ''.join(current).strip()
	if entry:
		entries.append(entry)
	return entries

def _iter_modifier_blocks(text: str, src: str) -> Iterator[ModifierBlock]:
	pat = re.compile(r'\bmodifier\s*=\s*{')
	pos = 0

	while True:
		m = pat.search(text, pos)
		if not m:
			break

		open_brace = text.find('{', m.end() - 1)
		if open_brace < 0:
			break

		close_brace = _find_matching_brace(text, open_brace)
		if close_brace < 0:
			break

		raw = text[m.start():close_brace + 1]
		body_str = text[open_brace + 1:close_brace]
		# Split body into lines/items (strip whitespace)
		entries = [line.strip() for line in body_str.splitlines() if line.strip()]

		modifiers: List[JobEffect] = []
		leftover: List[str] = []

		for entry in entries:
			eff: JobEffect = JobEffectParser.parse_any_job_effect(entry)
			if eff is not None:
				modifiers.append(eff)
			else:
				leftover.append(entry)

		if modifiers:
			yield JobModifierBlock(body=leftover, raw_text=raw, modifiers=modifiers)
		else:
			# No typed effects; preserve the entire body as individual lines
			yield ModifierBlock(body=leftover, raw_text=raw)

		pos = close_brace + 1

def _iter_triggered_country_modifier_blocks(text: str) -> Iterator[TriggeredCountryModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredCountryModifierBlock)


def _iter_triggered_planet_modifier_blocks(text: str) -> Iterator[TriggeredPlanetModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredPlanetModifierBlock)
