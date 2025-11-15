# -*- coding: utf-8 -*-
"""
civics_jobs.py — Parse Stellaris civics' effects on jobs and render a GTK tab.

What it does (first version):
- Parses `common/governments/civics/*.txt` for job-specific effects:
  * direct job count changes like: job_X_add = N
  * job output/upkeep changes like: planet_{researchers|artisans|farmers|...}_{produces|upkeep}_mult
- (Optional, later) We can extend to scan buildings/districts for civic-conditional job swaps.

UI:
- Provides CivicsJobsTab: a widget with:
  * Left: list (one line per civic that affects any job) with a human-readable summary
  * Right: filter panel with a searchable job list (toggle jobs to filter civics)
- Only civics that affect *some* job appear (others are omitted).

Notes:
- Clausewitz parsing here is pragmatic—not a full grammar. It’s good enough for civics modifiers.
- Indentation: tabs (user preference).
"""

import os
import re
import glob
from typing import Dict, List, Tuple, Optional, Set

from parsing.context import GlobalContext
from parsing.modifiers import _iter_modifier_blocks, _iter_triggered_country_modifier_blocks, _iter_triggered_planet_modifier_blocks
from parsing.parsing import _discover_jobs, _strip_comments
from parsing.types import CivicJobEffects, Job, JobEffect, JobModifierBlock

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject

DEBUG = True
def dbg(*a):
	if DEBUG:
		print("[civics_jobs]", *a)

# ----------------------------
# Localisation helpers
# ----------------------------

def _loc_get(loc: Dict[str, str], key: str) -> str:
	return loc.get(key, key)

def _job_name(loc: Dict[str, str], job_key: str) -> str:
	# Prefer singular job name if present
	return loc.get(job_key, job_key)

# ----------------------------
# Clausewitz parsing helpers (minimal)
# ----------------------------

def _top_blocks(text: str, prefix: str) -> List[Tuple[str, int, int]]:
	"""
	Find top-level blocks whose key starts with `prefix` (e.g., civic_... = { ... }).
	Returns a list of (key, body_start, body_end).
	"""
	blocks: List[Tuple[str, int, int]] = []
	pat = re.compile(r'\s*([A-Za-z0-9_\.]+)\s*=\s*{')
	i = 0
	in_str = False
	depth = 0
	while i < len(text):
		ch = text[i]
		if ch == '"':
			in_str = not in_str
			i += 1
			continue
		if depth == 0:
			m = pat.match(text, i)
			if m:
				key = m.group(1)
				if key.startswith(prefix):
					j = m.end(0)  # after '{'
					in_str2 = False
					depth2 = 1
					k = j
					while k < len(text):
						ch2 = text[k]
						if ch2 == '"':
							in_str2 = not in_str2
							k += 1
							continue
						if not in_str2:
							if ch2 == '{':
								depth2 += 1
							elif ch2 == '}':
								depth2 -= 1
								if depth2 == 0:
									# body is text[j:k]
									blocks.append((key, j, k))
									k += 1
									break
						k += 1
					i = k
					continue
		if not in_str:
			if ch == '{':
				depth += 1
			elif ch == '}':
				depth = max(0, depth - 1)
		i += 1
	return blocks

def _extract_block(body: str, name: str) -> List[str]:
	"""
	Extract zero or more blocks `name = { ... }` from body, return list of body strings.
	"""
	out: List[str] = []
	pat = re.compile(r'\b' + re.escape(name) + r'\s*=\s*{')
	i = 0
	while True:
		m = pat.search(body, i)
		if not m:
			break
		start = m.end(0)
		in_str = False
		depth = 1
		j = start
		while j < len(body):
			ch = body[j]
			if ch == '"':
				in_str = not in_str
				j += 1
				continue
			if not in_str:
				if ch == '{':
					depth += 1
				elif ch == '}':
					depth -= 1
					if depth == 0:
						out.append(body[start:j])
						i = j + 1
						break
			j += 1
		else:
			# Unbalanced, stop
			break
	return out

def _parse_triggered_jobs_blocks(text: str, loc: Dict[str, str], jobs: Optional[Dict[str, Job]], srcfile: str) -> Dict[str, List[JobEffect]]:
	"""
	Find blocks like:
	  triggered_jobs = {
		potential = { has_civic = civic_foo }
		job_research_director = 2
		job_politician = -2
	  }
	Return: civic_key -> [JobEffect, ...]
	"""

	def is_job(j: str) -> bool:
		return (jobs is None) or (j in jobs)

	def job_display_name(j: str) -> str:
		if jobs is not None and j in jobs:
			return jobs[j].name
		return _job_name(loc, j)

	result: Dict[str, List[JobEffect]] = {}
	for tb in _extract_block(text, "triggered_jobs"):
		# Collect all civics referenced in potential/limit/etc inside this block
		civics = set(re.findall(r'\bhas_civic\s*=\s*(civic_[A-Za-z0-9_]+)\b', tb))
		if not civics:
			continue
		# Find job deltas in the same block
		for jm in re.finditer(r'\b(job_[A-Za-z0-9_]+)\s*=\s*([+\-]?\d+)\b', tb):
			job_key, val = jm.group(1), jm.group(2)
			if not is_job(job_key):
				continue
			eff = JobEffect(job=GlobalContext.job_get(job_key), kind="count", value=val, scope="planet/building", source=srcfile, note="triggered_jobs")
			for ck in civics:
				result.setdefault(ck, []).append(eff)
	return result

def _parse_tpm_for_civic_jobs(tpm_text: str, loc: Dict[str, str], jobs: Optional[Dict[str, Job]], srcfile: str) -> Dict[str, List[JobEffect]]:
	def is_job(j: str) -> bool:
		return (jobs is None) or (j in jobs)

	civics = set(re.findall(r'\bhas_civic\s*=\s*(civic_[A-Za-z0-9_]+)\b', tpm_text))
	if not civics:
		return {}
	collected: List[JobEffect] = []

	for mod in _extract_block(tpm_text, "modifier"):
		collected.extend(_parse_effects_from_modifier(mod, loc, jobs, srcfile, "building/district TPM"))

	for jm in re.finditer(r'\b(job_[A-Za-z0-9_]+)\s*=\s*([+\-]?\d+)\b', tpm_text):
		jk, val = jm.group(1), jm.group(2)
		if is_job(jk):
			collected.append(JobEffect(job=GlobalContext.job_get(jk), kind="count", value=val, scope="planet/building", source=srcfile, note="TPM: add_jobs"))

	out: Dict[str, List[JobEffect]] = {}
	if collected:
		for ck in civics:
			out.setdefault(ck, []).extend(collected)
	return out

def _scan_job_swaps_from_assets(common_root: str, loc: Dict[str, str], jobs: Optional[Dict[str, Job]]) -> Dict[str, List[JobEffect]]:
	out: Dict[str, List[JobEffect]] = {}
	for sub in ("buildings","districts"):
		ad = os.path.join(common_root, sub)
		if not os.path.isdir(ad):
			dbg("missing assets dir:", ad)
			continue
		for path in sorted(glob.glob(os.path.join(ad, "*.txt"))):
			try:
				raw = open(path, "r", encoding="utf-8-sig").read()
			except Exception as e:
				dbg("read error:", path, e)
				continue
			text = _strip_comments(raw)

			found1 = _parse_triggered_jobs_blocks(text, loc, jobs or set(), os.path.basename(path))
			found2: Dict[str, List[JobEffect]] = {}
			for tpm in _extract_block(text, "triggered_planet_modifier"):
				mapped = _parse_tpm_for_civic_jobs(tpm, loc, jobs, os.path.basename(path))
				for ck, effs in mapped.items():
					found2.setdefault(ck, []).extend(effs)

			for d in (found1, found2):
				for ck, effs in d.items():
					out.setdefault(ck, []).extend(effs)
	dbg("job swaps found for", len(out), "civics")
	return out

# ----------------------------
# Effect extraction
# ----------------------------

# e.g. planet_researchers_society_research_produces_add = 1
_PLANET_GROUP_RES_RE = re.compile(
	r'\bplanet_([a-z_]+?)s_([a-z_]+)_(produces|upkeep)_(add|mult)\s*=\s*([+-]?\d+(?:\.\d+)?)'
)

PLANET_JOB_RESOURCE_RE = re.compile(
	r'\bplanet_([A-Za-z0-9_]+)s_([A-Za-z0-9_]+)_produces_(add|mult)\s*=\s*([+\-]?[0-9.]+)\b'
)

# e.g. physicist_jobs_bonus_workforce_mult = 0.02
JOBS_BONUS_WORKFORCE_RE = re.compile(
	r'\b([a-z_]+)_jobs_bonus_workforce_mult\s*=\s*([+-]?\d+(?:\.\d+)?)'
)

def _singular(plural: str) -> str:
	if plural.endswith('ies'):
		return plural[:-3] + 'y'
	if plural.endswith('ses'):
		return plural[:-2]  # e.g. "taxes" -> "taxe" (rare), but fine for most job names
	if plural.endswith('s'):
		return plural[:-1]
	return plural

# Special group→jobs expansion (because there is no 'job_researcher')
_GROUP_TO_JOBS = {
	'researcher': ['job_physicist', 'job_biologist', 'job_engineer'],
	# you can add other weird groups here if needed later
}

def _expand_group_to_jobs(group_base: str, known_jobs: Set[str]) -> List[str]:
	# group_base is singular form already (we pass singularized value below)
	if group_base in _GROUP_TO_JOBS:
		return _GROUP_TO_JOBS[group_base]
	# otherwise assume a straightforward singular job exists
	candidate = f'job_{group_base}'
	return [candidate] if candidate in known_jobs or not known_jobs else []


# Match direct job count modifiers: job_<id>_add = N
JOB_ADD_RE = re.compile(r'\b(job_[A-Za-z0-9_]+)_add\s*=\s*([+-]?\d+)\b')

# Match planet-level job production/upkeep modifiers:
#   planet_researchers_produces_mult = 0.15
#   planet_artisans_upkeep_mult = -0.1
PLANET_JOB_MULT_RE = re.compile(
	r'\bplanet_([A-Za-z0-9_]+)s_(produces_mult|upkeep_mult)\s*=\s*([+-]?[0-9.]+)\b'
)

# Some irregular plurals → job ids
_IRREGULAR = {
	"metallurgist": "job_metallurgist",
	"enforcer": "job_enforcer",
	"technician": "job_technician",
	"researcher": "job_researcher",
	"artisan": "job_artisan",
	"farmer": "job_farmer",
	"miner": "job_miner",
	"priest": "job_priest",
	"merchant": "job_merchant",
	"ruler": "job_ruler",
	"soldier": "job_soldier"
}

def _plural_to_job_id(plural_root: str) -> Optional[str]:
	"""
	Very small singularization for common job groups (researchers→job_researcher, etc.).
	We cover regular '...s' plus a few irregulars.
	"""
	root = plural_root.lower()
	# basic singularization
	if root.endswith("ists"):
		sing = root[:-1]   # metallurgists -> metallurgist
	elif root.endswith("ers"):
		sing = root[:-1]   # researchers -> researcher, miners -> miner
	elif root.endswith("ians"):
		sing = root[:-1]   # technicians -> technician
	elif root.endswith("s"):
		sing = root[:-1]
	else:
		sing = root

	if sing in _IRREGULAR:
		return _IRREGULAR[sing]
	return f"job_{sing}"

def _parse_effects_from_modifier(mod_text: str, loc: Dict[str, str], jobs: Optional[Dict[str, Job]], src: str, note: str) -> List[JobEffect]:
	def is_job(j: str) -> bool:
		return (jobs is None) or (j in jobs)

	effects: List[JobEffect] = []

	# A) job_*_add
	for m in JOB_ADD_RE.finditer(mod_text):
		jk, val = m.group(1), m.group(2)
		if is_job(jk):
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind="count", value=val, scope="country", source=src, note=note))

	# B1) planet_<plural>_(produces|upkeep)_mult
	for m in PLANET_JOB_MULT_RE.finditer(mod_text):
		plural, kind, val = m.group(1), m.group(2), m.group(3)
		if plural in ("jobs","pops"):
			continue
		jk = _plural_to_job_id(plural)
		if jk and is_job(jk):
			effects.append(JobEffect(GlobalContext.job_get(jk), kind=kind, value=val, scope="country", source=src, note=note))

	# B2) planet_<plural>_<resource>_produces_(add|mult)
	for m in PLANET_JOB_RESOURCE_RE.finditer(mod_text):
		plural, resource, mode, val = m.group(1), m.group(2), m.group(3), m.group(4)
		if plural in ("jobs","pops"):
			continue
		jk = _plural_to_job_id(plural)
		if jk and is_job(jk):
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind=f"produces_{mode}", value=val, scope="country", source=src, note=f"{note}; {resource}"))

	# C) job_<id>_(produces|upkeep)_mult
	for m in re.finditer(r'\b(job_[A-Za-z0-9_]+)_(produces_mult|upkeep_mult)\s*=\s*([+\-]?[0-9.]+)\b', mod_text):
		jk, kind, val = m.group(1), m.group(2), m.group(3)
		if is_job(jk):
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind=kind, value=val, scope="country", source=src, note=note))

	# D) job_<id>_<resource>_produces_(add|mult)
	for m in re.finditer(r'\b(job_[A-Za-z0-9_]+)_([A-Za-z0-9_]+)_produces_(add|mult)\s*=\s*([+\-]?[0-9.]+)\b', mod_text):
		jk, resource, mode, val = m.group(1), m.group(2), m.group(3), m.group(4)
		if is_job(jk):
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind=f"produces_{mode}", value=val, scope="country", source=src, note=f"{note}; {resource}"))

	# E) job_<id>_output[_add|_mult]
	for m in re.finditer(r'\b(job_[A-Za-z0-9_]+)_output(_(add|mult))?\s*=\s*([+\-]?[0-9.]+)\b', mod_text):
		jk, _, suffix, val = m.group(1), m.group(2), m.group(3), m.group(4)
		if is_job(jk):
			kind = "output" if not suffix else f"output_{suffix}"
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind=kind, value=val, scope="country", source=src, note=note))

	# F) <job-base>_jobs_bonus_workforce_mult
	for m in JOBS_BONUS_WORKFORCE_RE.finditer(mod_text):
		base, val = m.group(1), m.group(2)
		jk = f"job_{base}"
		if is_job(jk):
			effects.append(JobEffect(job=GlobalContext.job_get(jk), kind="bonus_workforce_mult", value=val, scope="country", source=src, note=note))

	return effects

def parse_civics_job_effects(common_root: str, loc: Dict[str, str]) -> Tuple[List[CivicJobEffects], Dict[str, Job]]:
	# Discover jobs
	job_map = _discover_jobs(common_root, loc)
	GlobalContext.set_global_context(job_map, loc)
	if len(job_map) == 0:
		dbg("WARNING: 0 jobs discovered — will NOT filter by known jobs (fallback enabled)")
		job_map = None  # disable filtering so we still see effects

	def _scan_dir(dir_path: str, block_prefix: str, name_prefix: str = "") -> Tuple[List[CivicJobEffects], Dict[str, str]]:
		files = sorted(glob.glob(os.path.join(dir_path, "*.txt")))
		dbg("scan", dir_path, "files:", len(files))
		found: List[CivicJobEffects] = []
		job_names: Dict[str, str] = {}

		for path in files:
			try:
				raw = open(path, "r", encoding="utf-8-sig").read()
			except Exception as e:
				dbg("read error:", path, e)
				continue
			text = _strip_comments(raw)

			for key, body_start, body_end in _top_blocks(text, block_prefix):
				body = text[body_start:body_end]
				effects: List[JobEffect] = []

				# Plain modifiers directly under the civic/origin block
				for mod_block in _iter_modifier_blocks(body, path):
					if isinstance(mod_block, JobModifierBlock):
						new_effects = mod_block.to_job_effects()
						if new_effects:
							effects.extend(new_effects)
					else:
						fallback = _parse_effects_from_modifier(
							mod_block.body,  # inner text of modifier
							loc,
							job_map,
							os.path.basename(path),
							"modifier"
						)
						if fallback:
							effects.extend(fallback)

				# Triggered country modifiers, each may contain its own modifier block(s)
				for tcm_block in _iter_triggered_country_modifier_blocks(body):
					for mod_block in _iter_modifier_blocks(tcm_block.body):
						effects.extend(
							_parse_effects_from_modifier(
								mod_block.body,
								loc,
								job_map,
								os.path.basename(path),
								"triggered_country_modifier"
							)
						)

				# Triggered planet modifiers, each may contain its own modifier block(s)
				for tpm_block in _iter_triggered_planet_modifier_blocks(body):
					for mod_block in _iter_modifier_blocks(tpm_block.body):
						effects.extend(
							_parse_effects_from_modifier(
								mod_block.body,
								loc,
								job_map,
								os.path.basename(path),
								"triggered_planet_modifier"
							)
						)

				if effects:
					display_name = f"{name_prefix}{_loc_get(loc, key)}"
					found.append(CivicJobEffects(key, display_name, effects))
					for eff in effects:
						job_names.setdefault(eff.job.key, eff.job.name)

		found.sort(key=lambda c: c.civic_name.lower())
		dbg(f"scan done: {block_prefix} -> {len(found)} entries with effects")
		return found, job_names

	# Civics & Origins
	civic_dir = os.path.join(common_root, "governments", "civics")
	orig_dir  = os.path.join(common_root, "origins")
	civics, jn_civ = _scan_dir(civic_dir, "civic_", "")
	origins, jn_org = _scan_dir(orig_dir,  "origin_", "[Origin] ")

	# Job swaps
	swap_map = _scan_job_swaps_from_assets(common_root, loc, job_map)
	if swap_map:
		index: Dict[str, CivicJobEffects] = {c.civic_key: c for c in civics}
		for ck, effs in swap_map.items():
			if ck not in index:
				index[ck] = CivicJobEffects(ck, _loc_get(loc, ck), [])
				civics.append(index[ck])
			index[ck].effects.extend(effs)
			for eff in effs:
				jn_civ.setdefault(eff.job.key, eff.job.name)

	# Finalize
	results = [c for c in civics if c.effects] + [o for o in origins if o.effects]
	results.sort(key=lambda x: x.civic_name.lower())

	for m in (jn_civ, jn_org):
		for k, v in m.items():
			job_map[k] = Job(key=k, name=v)

	dbg(f"FINAL: civics={len(civics)} origins={len(origins)} results={len(results)} jobs={len(job_map)}")
	return results, job_map

def _parse_group_resource_effects(buf: str, known_jobs: Set[str]) -> List[JobEffect]:
	effects: List[JobEffect] = []
	for m in _PLANET_GROUP_RES_RE.finditer(buf):
		plural_group, resource, kind, mode, val = m.groups()
		base = _singular(plural_group)
		for job_key in _expand_group_to_jobs(base, known_jobs):
			effects.append(JobEffect(
				job_key=job_key,
				effect_type=f"{kind}_{mode}",   # e.g. "produces_add", "upkeep_mult"
				resource=resource,
				value=float(val),
				source="group"
			))
	return effects

def _parse_jobs_bonus_workforce(buf: str, known_jobs: Set[str]) -> List[JobEffect]:
	effects: List[JobEffect] = []
	for m in GlobalContext.jobs_workforce_mult_re.finditer(buf):
		base, val = m.groups()
		for job_key in _expand_group_to_jobs(base, known_jobs):
			effects.append(JobEffect(
				job_key=job_key,
				effect_type="bonus_workforce_mult",
				resource=None,
				value=float(val),
				source="jobs_bonus"
			))
	return effects

# ----------------------------
# GTK Tab widget
# ----------------------------

class CivicsJobsTab(Gtk.Box):
	"""
	Split view:
	- Left: list of civics with their job effects (one row per civic)
	- Right: filters (searchable list of jobs with toggles). Selecting any jobs
	  filters the civic list to those that affect at least one of the selected jobs.
	"""

	__gsignals__ = {
		"filters-changed": (GObject.SignalFlags.RUN_FIRST, None, ())
	}

	def __init__(self, civics: List[CivicJobEffects], jobs: Dict[str, Job]):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
		self.set_hexpand(True)
		self.set_vexpand(True)

		self._civics = civics
		self._jobs = jobs
		self._selected_jobs: Set[str] = set()

		# Left pane — civic list
		self._civic_store = Gtk.ListStore(str, str, str)  # civic_name, civic_key, summary
		for c in civics:
			summary = self._make_summary(c)
			self._civic_store.append([c.civic_name, c.civic_key, summary])

		self._civic_filter = self._civic_store.filter_new()
		self._civic_filter.set_visible_func(self._civic_visible)

		civic_view = Gtk.TreeView(model=self._civic_filter)
		render_text = Gtk.CellRendererText()
		col1 = Gtk.TreeViewColumn("Civic", render_text, text=0)
		col2 = Gtk.TreeViewColumn("Effects (jobs)", Gtk.CellRendererText(), text=2)
		civic_view.append_column(col1)
		civic_view.append_column(col2)

		left_scroller = Gtk.ScrolledWindow()
		left_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		left_scroller.add(civic_view)

		# Right pane — job filters
		right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
		right_box.set_margin_top(6)
		right_box.set_margin_bottom(6)
		right_box.set_margin_start(6)
		right_box.set_margin_end(6)

		label = Gtk.Label(label="Filter by job")
		label.set_xalign(0.0)
		right_box.pack_start(label, False, False, 0)

		self._job_search = Gtk.SearchEntry()
		self._job_search.set_placeholder_text("Type to filter jobs… (e.g., researcher, artisan, farmer)")
		self._job_search.connect("search-changed", self._on_job_search_changed)
		right_box.pack_start(self._job_search, False, False, 0)

		self._job_store = Gtk.ListStore(bool, str, str)  # active, job_key, job_name
		for key, job in sorted(jobs.items(), key=lambda kv: kv[1].name.lower()):
			self._job_store.append([False, key, job.name])

		self._job_filter = self._job_store.filter_new()
		self._job_filter.set_visible_func(self._job_row_visible)

		job_view = Gtk.TreeView(model=self._job_filter)
		toggle = Gtk.CellRendererToggle()
		toggle.connect("toggled", self._on_job_toggled)
		col_toggle = Gtk.TreeViewColumn("Use", toggle, active=0)
		col_job = Gtk.TreeViewColumn("Job", Gtk.CellRendererText(), text=2)
		job_view.append_column(col_toggle)
		job_view.append_column(col_job)

		job_scroller = Gtk.ScrolledWindow()
		job_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		job_scroller.set_min_content_height(200)
		job_scroller.add(job_view)
		right_box.pack_start(job_scroller, True, True, 0)

		btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
		btn_clear = Gtk.Button.new_with_label("Clear filters")
		btn_clear.connect("clicked", self._on_clear_filters)
		btn_box.pack_start(btn_clear, False, False, 0)
		right_box.pack_start(btn_box, False, False, 0)

		paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
		paned.pack1(left_scroller, resize=True, shrink=False)
		paned.pack2(right_box, resize=False, shrink=False)
		self.pack_start(paned, True, True, 0)

	def _make_summary(self, c: CivicJobEffects) -> str:
		def _fmt_signed_int(s: str) -> str:
			try:
				# Some values are "1" or "1.0" – normalize to int when possible
				n = int(float(s))
				return f"{n:+d}"
			except Exception:
				try:
					f = float(s)
					return f"{f:+g}"
				except Exception:
					return s  # last-resort: raw

		def _fmt_pct(s: str) -> str:
			try:
				return f"{float(s) * 100:+.0f}%"
			except Exception:
				return s

		def _maybe_res(note: str) -> str:
			# We stuffed resource into note like "…; physics_research" or "…; sr_dark_matter"
			if note and "; " in note:
				return f" ({note.split('; ', 1)[1]})"
			return ""

		parts: List[str] = []
		for eff in c.effects:
			if eff.kind == "count":
				parts.append(f"{eff.job.name} {_fmt_signed_int(eff.value)}")
			elif eff.kind in ("produces_mult", "upkeep_mult", "output_mult", "bonus_workforce_mult"):
				label = "prod" if eff.kind.startswith("produces") else (
					"upkeep" if eff.kind.startswith("upkeep") else (
						"output" if "output" in eff.kind else "workforce"
					)
				)
				parts.append(f"{eff.job.name} {_fmt_pct(eff.value)} {label}{_maybe_res(eff.note)}")
			elif eff.kind in ("produces_add", "output", "output_add"):
				label = "prod" if eff.kind.startswith("produces") else "output"
				parts.append(f"{eff.job.name} {eff.value} {label}{_maybe_res(eff.note)}")
			else:
				# Unknown/new kind – don’t drop it, display raw
				parts.append(f"{eff.job.name} {eff.kind}={eff.value}{_maybe_res(eff.note)}")

		return "; ".join(parts) if parts else "—"

	# ---- Civic filter logic

	# Before:
	# def _civic_visible(self, model, iter_) -> bool:
	# After:
	def _civic_visible(self, model, iter_, data) -> bool:
		if not self._selected_jobs:
			return True
		civic_key = model[iter_][1]
		if not hasattr(self, "_civic_to_jobs"):
			self._civic_to_jobs: Dict[str, Set[str]] = {}
			for c in self._civics:
				jset = {e.job_key for e in c.effects}
				self._civic_to_jobs[c.civic_key] = jset
		jset = self._civic_to_jobs.get(civic_key, set())
		return bool(self._selected_jobs.intersection(jset))

	# Before:
	# def _job_row_visible(self, model, iter_) -> bool:
	# After (same reason: TreeModelFilter also calls with user_data):
	def _job_row_visible(self, model, iter_, data) -> bool:
		query = (self._job_search.get_text() or "").strip().lower()
		if not query:
			return True
		job_key = model[iter_][1]
		job_name = (model[iter_][2] or "").lower()
		synonyms = {"physicist": "researcher"}
		if query in synonyms:
			query = synonyms[query]
		return (query in job_name) or (query in job_key.lower())

	def _on_job_toggled(self, cell, path_str):
		it = self._job_filter.get_iter(path_str)
		if not it:
			return
		# Translate filter iter to child store iter
		child_it = self._job_filter.convert_iter_to_child_iter(it)
		active, job_key, _ = self._job_store[child_it]
		active = not active
		self._job_store[child_it][0] = active

		if active:
			self._selected_jobs.add(job_key)
		else:
			self._selected_jobs.discard(job_key)

		self._civic_filter.refilter()
		self.emit("filters-changed")

	def _on_job_search_changed(self, entry):
		self._job_filter.refilter()

	def _on_clear_filters(self, btn):
		self._selected_jobs.clear()
		for row in self._job_store:
			row[0] = False
		self._civic_filter.refilter()
		self.emit("filters-changed")
