import glob
import os
import re

from typing import Dict, Iterator, Type, TypeVar

from .types import BlockBase, Job, ModifierBlock, TriggeredCountryModifierBlock, TriggeredPlanetModifierBlock

# Top-level “key = { … }” matcher (jobs have bare keys like 'physicist', 'clerk', etc.)
_JOB_DEF_START = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*{', re.M)

_SKIP_TOP_KEYS = {
	# common container keys we might bump into; we only want actual job blocks
	'country', 'species', 'planet', 'triggered_planet_modifier', 'triggered_country_modifier',
	'resources', 'upkeep', 'produces', 'possible', 'possible_pre_triggers', 'possible_precalc',
	'promotion', 'demotion', 'weight', 'planet_modifier', 'inline_script', 'swappable_data',
	'overlord_resources', 'tags', 'category'
}

DEBUG = True
def dbg(*a):
	if DEBUG:
		print("[civics_jobs]", *a)

def _find_matching_brace(s: str, open_pos: int) -> int:
	"""Given s[open_pos] == '{', find the matching '}' position (or -1)."""
	depth = 0
	for i in range(open_pos, len(s)):
		ch = s[i]
		if ch == '{':
			depth += 1
		elif ch == '}':
			depth -= 1
			if depth == 0:
				return i
	return -1

def _strip_comments(text: str) -> str:
	out = []
	in_str = False
	i = 0
	while i < len(text):
		ch = text[i]
		if ch == '"':
			in_str = not in_str
			out.append(ch)
			i += 1
			continue
		if not in_str and ch == '#':
			while i < len(text) and text[i] != '\n':
				i += 1
			continue
		out.append(ch)
		i += 1
	return "".join(out)

def _discover_jobs(common_root: str, loc: Dict[str, str]) -> Dict[str, Job]:
	pop_jobs_dir = os.path.join(common_root, "pop_jobs")
	dbg("discover jobs in:", pop_jobs_dir)

	jobs: Dict[str, Job] = {}

	if not os.path.isdir(pop_jobs_dir):
		dbg("WARNING: pop_jobs dir missing")
		return jobs

	for path in sorted(glob.glob(os.path.join(pop_jobs_dir, "*.txt"))):
		try:
			raw = open(path, "r", encoding="utf-8-sig").read()
		except Exception as e:
			dbg("read error:", path, e)
			continue

		text = _strip_comments(raw)

		for m in _JOB_DEF_START.finditer(text):
			top_key = m.group(1)
			if top_key in _SKIP_TOP_KEYS:
				continue

			open_brace = text.find('{', m.end() - 1)
			if open_brace == -1:
				continue
			close_brace = _find_matching_brace(text, open_brace)
			if close_brace == -1:
				continue

			body = text[open_brace:close_brace]
			# Heuristic: real job definitions have a "category = ..." line
			if re.search(r'\bcategory\s*=\s*[A-Za-z_]+', body) is None:
				continue

			job_key = f"job_{top_key}"
			if job_key in jobs:
				continue

			job_name = loc.get(job_key, job_key)
			jobs[job_key] = Job(key=job_key, name=job_name)

	dbg(f"discovered {len(jobs)} jobs")
	if jobs:
		sample = sorted(jobs.keys())[:10]
		dbg("sample jobs:", sample)

	return jobs


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
