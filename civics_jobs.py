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
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject

# ----------------------------
# Data types
# ----------------------------

@dataclass
class JobEffect:
	job_key: str                  # e.g., job_researcher
	job_name: str                 # localized single-name (e.g., Researcher)
	kind: str                     # "count", "produces_mult", "upkeep_mult"
	value: str                    # as string (keep constants/decimals intact)
	scope: str                    # "country" (typical civic modifiers)
	source: str                   # file base (for reference)
	note: str = ""                # optional short note / path inside civic

@dataclass
class CivicJobEffects:
	civic_key: str
	civic_name: str
	effects: List[JobEffect] = field(default_factory=list)

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

# ----------------------------
# Effect extraction
# ----------------------------

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

def _parse_effects_from_modifier(mod_text: str, loc: Dict[str, str], src: str, note: str) -> List[JobEffect]:
	effects: List[JobEffect] = []

	# Direct job counts
	for m in JOB_ADD_RE.finditer(mod_text):
		job_key, val = m.group(1), m.group(2)
		effects.append(JobEffect(
			job_key=job_key,
			job_name=_job_name(loc, job_key),
			kind="count",
			value=val,
			scope="country",
			source=src,
			note=note
		))

	# Planet job production / upkeep multipliers (job-group specific)
	for m in PLANET_JOB_MULT_RE.finditer(mod_text):
		plural, kind, val = m.group(1), m.group(2), m.group(3)
		job_key = _plural_to_job_id(plural)
		if not job_key:
			continue
		effects.append(JobEffect(
			job_key=job_key,
			job_name=_job_name(loc, job_key),
			kind=kind,  # "produces_mult" or "upkeep_mult"
			value=val,
			scope="country",
			source=src,
			note=note
		))

	return effects

def parse_civics_job_effects(common_root: str, loc: Dict[str, str]) -> Tuple[List[CivicJobEffects], Dict[str, str]]:
	"""
	Parse all civics AND origins for job effects and return:
	  - list of CivicJobEffects (one entry per civic/origin, only if it has job effects)
	  - job_name_map: job_key -> localized name (for filter UI)

	We scan:
	  - common/governments/civics/*.txt   (blocks: civic_*)
	  - common/origins/*.txt               (blocks: origin_*)
	Looking for:
	  - modifier = { job_*_add, planet_*s_{produces,upkeep}_mult }
	  - triggered_country_modifier = { modifier = { ... } }
	  - triggered_planet_modifier  = { modifier = { ... } }
	"""

	def _scan_dir(dir_path: str, block_prefix: str, name_prefix: str = "") -> Tuple[List[CivicJobEffects], Dict[str, str]]:
		files = sorted(glob.glob(os.path.join(dir_path, "*.txt")))
		found: List[CivicJobEffects] = []
		job_names: Dict[str, str] = {}

		for path in files:
			try:
				with open(path, "r", encoding="utf-8-sig") as f:
					raw = f.read()
			except Exception:
				continue

			text = _strip_comments(raw)
			for key, body_start, body_end in _top_blocks(text, block_prefix):
				body = text[body_start:body_end]

				effects: List[JobEffect] = []

				# Inline (country) modifier
				for mod in _extract_block(body, "modifier"):
					effects.extend(_parse_effects_from_modifier(mod, loc, os.path.basename(path), "modifier"))

				# Triggered country modifier(s)
				for tcm in _extract_block(body, "triggered_country_modifier"):
					for mod in _extract_block(tcm, "modifier"):
						effects.extend(_parse_effects_from_modifier(mod, loc, os.path.basename(path), "triggered_country_modifier"))

				# Triggered planet modifier(s)
				for tpm in _extract_block(body, "triggered_planet_modifier"):
					for mod in _extract_block(tpm, "modifier"):
						effects.extend(_parse_effects_from_modifier(mod, loc, os.path.basename(path), "triggered_planet_modifier"))

				if effects:
					display_name = f"{name_prefix}{_loc_get(loc, key)}"
					found.append(CivicJobEffects(
						civic_key=key,
						civic_name=display_name,
						effects=effects
					))
					for eff in effects:
						job_names.setdefault(eff.job_key, eff.job_name)

		# Sort by display name for stable UI
		found.sort(key=lambda c: c.civic_name.lower())
		return found, job_names

	# Civics
	civic_dir = os.path.join(common_root, "governments", "civics")
	civics, job_names_civ = _scan_dir(civic_dir, "civic_", name_prefix="")

	# Origins
	origin_dir = os.path.join(common_root, "origins")
	origins, job_names_org = _scan_dir(origin_dir, "origin_", name_prefix="[Origin] ")

	# Merge results
	results = civics + origins
	job_names_all = {**job_names_civ}
	for k, v in job_names_org.items():
		job_names_all.setdefault(k, v)

	return results, job_names_all


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

	def __init__(self, civics: List[CivicJobEffects], job_names: Dict[str, str]):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
		self.set_hexpand(True)
		self.set_vexpand(True)

		self._civics = civics
		self._job_names = job_names
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
		all_jobs = sorted(job_names.items(), key=lambda kv: kv[1].lower())
		for jk, jn in all_jobs:
			self._job_store.append([False, jk, jn])

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
		"""
		Compact single-line summary, e.g.:
		"Researcher +1; Artisan +10% prod; Farmer -5% upkeep"
		"""
		parts: List[str] = []
		for eff in c.effects:
			if eff.kind == "count":
				parts.append(f"{eff.job_name} {eff.value:+}")
			elif eff.kind == "produces_mult":
				try:
					val = float(eff.value)
					parts.append(f"{eff.job_name} {val*100:+.0f}% prod")
				except Exception:
					parts.append(f"{eff.job_name} {eff.value} prod")
			elif eff.kind == "upkeep_mult":
				try:
					val = float(eff.value)
					parts.append(f"{eff.job_name} {val*100:+.0f}% upkeep")
				except Exception:
					parts.append(f"{eff.job_name} {eff.value} upkeep")
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
