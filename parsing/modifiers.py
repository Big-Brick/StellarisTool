import re

from typing import Iterator, List, Type, TypeVar

from .context import GlobalContext, Job, Resource
from .parsing import _find_matching_brace
from .types import BlockBase, ModifierBlock, PlanetJobProduceAddModifier, TriggeredCountryModifierBlock, TriggeredPlanetModifierBlock, JobEffectProductionAdd

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


def _iter_modifier_blocks(
	text: str,
	src: str
) -> Iterator[ModifierBlock]:
	"""
	Iterate over all 'modifier = { ... }' blocks in the given text.

	For blocks where we can successfully parse all
	    planet_<group>_<resource>_produces_add = <amount>
	lines into JobEffectProductionAdd, yield a PlanetJobProduceAddModifier.

	Otherwise, yield a plain ModifierBlock.
	"""
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
		body = text[open_brace + 1:close_brace]

		# Try to build a typed PlanetJobProduceAddModifier
		try:
			mods: List[JobEffectProductionAdd] = []

			for mm in GlobalContext.planet_job_produces_add_re.finditer(body):
				group = mm.group("group")
				res_key = mm.group("res")
				amount_str = mm.group("amount")
				amount = int(amount_str)

				# group -> job key, same heuristic as old code:
				base = group[:-1] if group.endswith("s") else group
				job_key = f"job_{base}"

				job: Job = GlobalContext.job_get(job_key)
				if job is None:
					raise ValueError(f"Unknown job key '{job_key}' derived from group '{group}'")

				resource: Resource = GlobalContext.resource_from_key(res_key)

				eff = JobEffectProductionAdd(
					job=job,
					resource=resource,
					amount=amount,
					scope="unk",
					source=src,
					note="",
				)
				mods.append(eff)

			if mods:
				yield PlanetJobProduceAddModifier(
					body=body,
					raw_text=raw,
					modifiers=mods
				)
			else:
				# no planet_*_produces_add lines — just a normal modifier
				yield ModifierBlock(body=body, raw_text=raw)

		except Exception as e:
			print(
				f"[typed-mod PlanetJobProduceAdd] failed in {src}: {e}. "
				"Falling back to generic ModifierBlock."
			)
			yield ModifierBlock(body=body, raw_text=raw)

		pos = close_brace + 1



def _iter_triggered_country_modifier_blocks(text: str) -> Iterator[TriggeredCountryModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredCountryModifierBlock)


def _iter_triggered_planet_modifier_blocks(text: str) -> Iterator[TriggeredPlanetModifierBlock]:
	return _iter_blocks_of_type(text, TriggeredPlanetModifierBlock)
