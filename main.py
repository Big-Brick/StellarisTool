#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stellaris Tech Tree (first version)
- Entry point: main.py
- Expects:
    ./data/common/technology/*.txt
    ./data/localisation/*_l_english.yml (or subfolders)
- Renders 3 tabs (Physics / Society / Engineering) in a GTK window.
- Each tech node shows name; hover tooltip shows tier, cost, categories,
  prerequisites, base weight and weight modifiers.

Notes:
- This is a pragmatic parser for Clausewitz format. It handles the common
  cases used in technology files: constants (@name = number), top-level tech
  blocks, and simple fields. It is not a full grammar.
- Weight modifiers are kept mostly as raw text for now.
"""

import os
import re
import sys
import glob
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --- Localisation -------------------------------------------------------------

def load_localisation(loc_root: str, language: str = "english") -> Dict[str, str]:
	"""
	Load Paradox-style localisation. We only need id->string for names and can
	live without strict YAML. Many lines look like:
	  key:0 "Text"
	We parse them with regex under sections like `l_english:`.
	"""
	loc_map: Dict[str, str] = {}

	# Collect all files that look like *_l_english.yml (recursively).
	pattern = os.path.join(loc_root, "**", f"*__l_{language}.yml")  # Paradox sometimes uses double underscore
	pattern2 = os.path.join(loc_root, "**", f"* _l_{language}.yml")  # just in case of stray spaces
	pattern3 = os.path.join(loc_root, "**", f"*_l_{language}.yml")
	files = set(glob.glob(pattern, recursive=True) + glob.glob(pattern2, recursive=True) + glob.glob(pattern3, recursive=True))

	# Fallback: also scan plain .yml if language segment is absent (rare)
	if not files:
		files = set(glob.glob(os.path.join(loc_root, "**", "*.yml"), recursive=True))

	section_re = re.compile(r'^\s*l_' + re.escape(language) + r'\s*:\s*$', re.IGNORECASE)
	line_re = re.compile(r'^\s*([A-Za-z0-9_.:-]+)\s*:\s*\d+\s+"(.*)"\s*$')

	for path in files:
		try:
			with open(path, "r", encoding="utf-8-sig") as f:
				in_section = False
				for raw in f:
					line = raw.rstrip("\n")
					if not in_section:
						if section_re.match(line):
							in_section = True
						continue
					# Stop if another section begins
					if line.strip().startswith("l_") and line.strip().endswith(":") and not section_re.match(line):
						in_section = False
						continue
					m = line_re.match(line)
					if m:
						key, text = m.group(1), m.group(2)
						# Unescape basic sequences
						text = text.replace("\\n", "\n").replace("\\\"", "\"")
						loc_map[key] = text
		except Exception:
			# Ignore malformed files; this is a best-effort loader.
			continue

	return loc_map


# --- Clausewitz / tech parsing ------------------------------------------------

@dataclass
class WeightModifier:
	kind: str  # "factor" or "add" or "raw"
	value: str
	condition: str  # raw trigger text inside the modifier block

@dataclass
class Tech:
	key: str
	name: str
	area: str
	tier: int
	cost: str
	categories: List[str]
	prerequisites: List[str]
	weight_base: str
	weight_modifiers: List[WeightModifier] = field(default_factory=list)
	flags: Dict[str, bool] = field(default_factory=dict)  # start_tech, is_rare, is_dangerous

class ClausewitzTechParser:
	def __init__(self, common_root: str, loc_map: Dict[str, str]):
		self.common_root = common_root
		self.loc = loc_map

	# --- utilities -----------------------------------------------------------

	@staticmethod
	def _strip_comments(text: str) -> str:
		# Remove #... to end-of-line, keeping content inside quotes
		out = []
		in_str = False
		i = 0
		while i < len(text):
			c = text[i]
			if c == '"':
				in_str = not in_str
				out.append(c)
				i += 1
				continue
			if not in_str and c == '#':
				# skip to EOL
				while i < len(text) and text[i] != '\n':
					i += 1
				continue
			out.append(c)
			i += 1
		return "".join(out)

	@staticmethod
	def _find_blocks(text: str, header_regex: re.Pattern) -> List[Tuple[str, int, int]]:
		"""
		Find top-level blocks like:
		  tech_xxx = { ...balanced... }
		Returns list of (key, start_index_of_body, end_index_after_body_brace).
		"""
		blocks = []
		i = 0
		in_str = False
		depth = 0
		while i < len(text):
			if text[i] == '"':
				in_str = not in_str
				i += 1
				continue
			if depth == 0:
				m = header_regex.match(text, i)
				if m:
					key = m.group(1)
					# position after the first '{'
					j = m.end(0)
					# Now find matching closing brace for this block
					in_str2 = False
					depth2 = 1
					k = j
					while k < len(text):
						ch = text[k]
						if ch == '"':
							in_str2 = not in_str2
							k += 1
							continue
						if not in_str2:
							if ch == '{':
								depth2 += 1
							elif ch == '}':
								depth2 -= 1
								if depth2 == 0:
									blocks.append((key, j, k))
									k += 1
									break
						k += 1
					i = k
					continue
			# update global depth to avoid false positives (not strictly required here)
			if not in_str:
				if text[i] == '{':
					depth += 1
				elif text[i] == '}':
					depth = max(0, depth - 1)
			i += 1
		return blocks

	@staticmethod
	def _read_const_table(text: str) -> Dict[str, str]:
		# @const = number
		consts = {}
		for m in re.finditer(r'@([A-Za-z0-9_]+)\s*=\s*([0-9.]+)', text):
			consts[m.group(1)] = m.group(2)
		return consts

	@staticmethod
	def _resolve_value(val: str, consts: Dict[str, str]) -> str:
		val = val.strip()
		if val.startswith("@"):
			name = val[1:]
			return consts.get(name, val)
		return val

	@staticmethod
	def _extract_block_text(body: str, key: str) -> Optional[str]:
		"""
		Extract the text of `key = { ... }` from within body (first occurrence).
		"""
		# find 'key' then '=' then '{'
		pattern = re.compile(r'\b' + re.escape(key) + r'\s*=\s*{')
		m = pattern.search(body)
		if not m:
			return None
		start = m.end(0)
		# match braces within this region
		in_str = False
		depth = 1
		i = start
		while i < len(body):
			ch = body[i]
			if ch == '"':
				in_str = not in_str
				i += 1
				continue
			if not in_str:
				if ch == '{':
					depth += 1
				elif ch == '}':
					depth -= 1
					if depth == 0:
						return body[start:i]
			i += 1
		return None

	@staticmethod
	def _extract_simple_value(body: str, key: str) -> Optional[str]:
		m = re.search(r'\b' + re.escape(key) + r'\s*=\s*([^\s#\n\r{}]+)', body)
		return m.group(1) if m else None

	@staticmethod
	def _extract_flag(body: str, key: str) -> Optional[bool]:
		m = re.search(r'\b' + re.escape(key) + r'\s*=\s*(yes|no)', body)
		if not m:
			return None
		return True if m.group(1) == "yes" else False

	@staticmethod
	def _parse_list_of_tokens(block_text: str) -> List[str]:
		# Accept tokens like: { a b "c" d }
		items = []
		for tok in re.findall(r'"([^"]+)"|([A-Za-z0-9_.:-]+)', block_text):
			if tok[0]:
				items.append(tok[0])
			elif tok[1]:
				items.append(tok[1])
		return items

	@staticmethod
	def _summarize_modifiers(wm_text: str, consts: Dict[str, str]) -> List[WeightModifier]:
		"""
		Parse weight_modifier block crudely: find modifier = { ... } and extract
		'factor = X' or 'add = Y' and leave the rest of the block as raw condition text.
		Also include lines outside 'modifier' (e.g., research_leader blocks) as raw entries.
		"""
		out: List[WeightModifier] = []

		# First, remove nested research_leader block(s) and turn them into raw summaries.
		# We keep a shortened single-line summary.
		offset = 0
		while True:
			blk = ClausewitzTechParser._extract_named_block_any(wm_text, "research_leader")
			if not blk:
				break
			full, content, start, end = blk
			# Derive a short summary: pull lines with factor/add and hinted expertise/traits
			lines = []
			for ln in content.splitlines():
				ln = ln.strip()
				if not ln:
					continue
				if ln.startswith(("factor", "add", "has_trait", "has_expertise", "area", "category")):
					lines.append(ln)
			summary = "; ".join(lines) if lines else content.strip().replace("\n", " ")
			out.append(WeightModifier(kind="raw", value="", condition=f"research_leader: {summary}"))
			# Remove this block so 'modifier' search does not get confused
			wm_text = wm_text[:start] + wm_text[end:]
			offset = start

		# Now, find modifier blocks.
		while True:
			blk = ClausewitzTechParser._extract_named_block_any(wm_text, "modifier")
			if not blk:
				break
			full, content, start, end = blk
			# Extract factor/add
			mfac = re.search(r'\bfactor\s*=\s*([^\s#\n\r{}]+)', content)
			madd = re.search(r'\badd\s*=\s*([^\s#\n\r{}]+)', content)
			val = ""
			kind = "raw"
			if mfac:
				kind = "factor"
				val = ClausewitzTechParser._resolve_value(mfac.group(1), consts)
			elif madd:
				kind = "add"
				val = ClausewitzTechParser._resolve_value(madd.group(1), consts)
			# Remove the factor/add line from condition and keep the rest as summary
			cond_lines = []
			for ln in content.splitlines():
				lns = ln.strip()
				if not lns:
					continue
				if (mfac and "factor" in lns) or (madd and re.search(r'\badd\s*=', lns)):
					continue
				cond_lines.append(lns)
			condition = " ".join(cond_lines)
			out.append(WeightModifier(kind=kind, value=val, condition=condition))
			wm_text = wm_text[:start] + wm_text[end:]

		# Anything left (non-empty) becomes a raw summary.
		leftover = wm_text.strip()
		if leftover:
			oneliner = " ".join([ln.strip() for ln in leftover.splitlines() if ln.strip()])
			out.append(WeightModifier(kind="raw", value="", condition=oneliner))

		return out

	@staticmethod
	def _extract_named_block_any(text: str, name: str) -> Optional[Tuple[str, str, int, int]]:
		"""
		Find first occurrence of `name = { ... }` in text and return:
		(full_block_text, body_text, start_idx, end_idx)
		"""
		m = re.search(r'\b' + re.escape(name) + r'\s*=\s*{', text)
		if not m:
			return None
		start = m.start()
		body_start = m.end()
		in_str = False
		depth = 1
		i = body_start
		while i < len(text):
			ch = text[i]
			if ch == '"':
				in_str = not in_str
				i += 1
				continue
			if not in_str:
				if ch == '{':
					depth += 1
				elif ch == '}':
					depth -= 1
					if depth == 0:
						end = i + 1
						return (text[start:end], text[body_start:i], start, end)
			i += 1
		return None

	def parse(self) -> Dict[str, Tech]:
		tech_dir = os.path.join(self.common_root, "technology")
		files = sorted(glob.glob(os.path.join(tech_dir, "*.txt")))
		techs: Dict[str, Tech] = {}

		header_re = re.compile(r'\s*([A-Za-z0-9_\.]+)\s*=\s*{')  # tech_xxx = {

		for path in files:
			with open(path, "r", encoding="utf-8-sig") as f:
				raw = f.read()

			text = self._strip_comments(raw)
			consts = self._read_const_table(text)

			# Discover top-level tech blocks
			for key, body_start, body_end in self._find_blocks(text, header_re):
				# Body is text[body_start:body_end]
				body = text[body_start:body_end]

				# We only care about "tech_*" blocks
				if not key.startswith("tech_"):
					continue

				area = self._extract_simple_value(body, "area") or "unknown"
				tier_s = self._extract_simple_value(body, "tier") or "0"
				try:
					tier = int(re.sub(r'[^0-9-]', '', tier_s))
				except Exception:
					tier = 0

				cost_raw = self._extract_simple_value(body, "cost") or ""
				cost = self._resolve_value(cost_raw, consts) if cost_raw else ""

				# Categories (field(s): voidcraft, particles, biology, etc.)
				cat_block = self._extract_block_text(body, "category")
				categories = self._parse_list_of_tokens(cat_block) if cat_block else []

				# Prerequisites (keys)
				pre_block = self._extract_block_text(body, "prerequisites")
				prerequisites = []
				if pre_block:
					# Usually quoted. Accept both quoted and bare tokens.
					prerequisites = self._parse_list_of_tokens(pre_block)

				# Weight
				weight_raw = self._extract_simple_value(body, "weight") or ""
				weight = self._resolve_value(weight_raw, consts) if weight_raw else ""

				# Weight modifiers (raw summary)
				wm_block = self._extract_block_text(body, "weight_modifier")
				modifiers: List[WeightModifier] = []
				if wm_block:
					modifiers = self._summarize_modifiers(wm_block, consts)

				# Flags
				flags = {}
				for fl in ("start_tech", "is_rare", "is_dangerous"):
					val = self._extract_flag(body, fl)
					if val is not None:
						flags[fl] = val

				# Human-readable name (fallback to key)
				name = self.loc.get(key, key)

				techs[key] = Tech(
					key=key,
					name=name,
					area=area,
					tier=tier,
					cost=cost,
					categories=categories,
					prerequisites=prerequisites,
					weight_base=weight,
					weight_modifiers=modifiers,
					flags=flags
				)

		return techs


# --- GTK UI ------------------------------------------------------------------

import gi
gi.require_version("Gtk", "3.0")
gi.require_foreign("cairo")  # tell GI we’ll use pycairo bindings
from gi.repository import Gtk, Gdk, Pango, GLib, GObject
import cairo  # <- this must be pycairo

NODE_W = 220
NODE_H = 64
H_SPACING = 100
V_SPACING = 18
MARGIN = 24

class TechNodeLayout:
	def __init__(self, tech: Tech, x: int, y: int):
		self.tech = tech
		self.x = x
		self.y = y

	def rect(self) -> Tuple[int, int, int, int]:
		return (self.x, self.y, NODE_W, NODE_H)

class TechAreaCanvas(Gtk.DrawingArea):
	__gsignals__ = {
		"tech-clicked": (GObject.SIGNAL_RUN_FIRST, None, (str,)),  # key
	}

	def __init__(self, area_name: str, techs: List[Tech], key_to_name: Dict[str, str]):
		super().__init__()
		self.set_has_window(False)
		self.set_size_request(600, 400)
		self.set_hexpand(True)
		self.set_vexpand(True)
		self.set_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
		self.set_has_tooltip(True)

		self.area_name = area_name
		self.techs = [t for t in techs if t.area == area_name]
		self.key_to_name = key_to_name

		# Build columns by tier
		self.columns: Dict[int, List[Tech]] = {}
		for t in self.techs:
			self.columns.setdefault(t.tier, []).append(t)

		# Sort tiers ascending; treat non-positive tiers as 0, repeatables often tier 5+ or -1
		self.tiers_sorted = sorted(self.columns.keys())
		# Sort techs in a tier by name
		for k in self.columns:
			self.columns[k].sort(key=lambda t: t.name.lower())

		# Compute layout once
		self.nodes: Dict[str, TechNodeLayout] = {}
		self.total_w, self.total_h = self._compute_layout()

		self.connect("draw", self.on_draw)
		self.connect("button-press-event", self.on_button_press)
		self.connect("query-tooltip", self.on_query_tooltip)

	def _compute_layout(self) -> Tuple[int, int]:
		x = MARGIN
		max_h = 0
		for i, tier in enumerate(self.tiers_sorted):
			col = self.columns[tier]
			y = MARGIN
			for tech in col:
				self.nodes[tech.key] = TechNodeLayout(tech, x, y)
				y += NODE_H + V_SPACING
			col_h = y - V_SPACING + MARGIN
			max_h = max(max_h, col_h)
			x += NODE_W + H_SPACING
		total_w = x - H_SPACING + MARGIN if self.tiers_sorted else 800
		total_h = max_h if self.tiers_sorted else 600
		# Resize drawing area to fit
		self.set_size_request(total_w, total_h)
		return total_w, total_h

	def _draw_node(self, cr: cairo.Context, node: TechNodeLayout):
		x, y, w, h = node.rect()
		tech = node.tech

		# Box
		radius = 8.0
		self._rounded_rect(cr, x, y, w, h, radius)
		# Fill based on flags/category hints
		if tech.flags.get("is_dangerous", False):
			cr.set_source_rgb(0.95, 0.85, 0.85)
		elif tech.flags.get("is_rare", False):
			cr.set_source_rgb(0.90, 0.92, 0.98)
		else:
			cr.set_source_rgb(0.94, 0.94, 0.94)
		cr.fill_preserve()
		cr.set_source_rgb(0.2, 0.2, 0.2)
		cr.set_line_width(1.0)
		cr.stroke()

		# Title
		cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
		cr.set_font_size(12)
		self._draw_text(cr, tech.name, x + 8, y + 18, w - 16)

		# Subtitle line: tier, cost
		cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
		cr.set_font_size(10)
		subtitle = f"Tier {tech.tier} • Cost {tech.cost or '?'}"
		self._draw_text(cr, subtitle, x + 8, y + 36, w - 16)

		# Categories
		cats = ", ".join(tech.categories) if tech.categories else "-"
		self._draw_text(cr, cats, x + 8, y + 52, w - 16)

	@staticmethod
	def _rounded_rect(cr: cairo.Context, x, y, w, h, r):
		cr.new_sub_path()
		cr.arc(x + w - r, y + r, r, -90 * (3.14159/180), 0)
		cr.arc(x + w - r, y + h - r, r, 0, 90 * (3.14159/180))
		cr.arc(x + r, y + h - r, r, 90 * (3.14159/180), 180 * (3.14159/180))
		cr.arc(x + r, y + r, r, 180 * (3.14159/180), 270 * (3.14159/180))
		cr.close_path()

	@staticmethod
	def _draw_text(cr: cairo.Context, text: str, x: int, y: int, width: int):
		# Simple single-line elide
		layout_text = text.replace("\n", " ")
		# cairo toy text API lacks Pango; keep simple; truncate if too long
		max_chars = 64
		if len(layout_text) > max_chars:
			layout_text = layout_text[:max_chars-1] + "…"
		cr.move_to(x, y)
		cr.show_text(layout_text)

	def _draw_edges(self, cr: cairo.Context):
		# Draw edges only for prerequisites within the same area to keep first version simple
		cr.set_source_rgba(0, 0, 0, 0.35)
		cr.set_line_width(1.0)
		for key, node in self.nodes.items():
			tech = node.tech
			for pre in tech.prerequisites:
				if pre in self.nodes:
					# Draw from prereq node right edge to this node left edge
					pnode = self.nodes[pre]
					x1 = pnode.x + NODE_W
					y1 = pnode.y + NODE_H // 2
					x2 = node.x
					y2 = node.y + NODE_H // 2
					# Simple straight line with small horizontal inset
					cr.move_to(x1 + 2, y1)
					cr.line_to(x2 - 2, y2)
					cr.stroke()

	def on_draw(self, widget, cr: cairo.Context):
		# Background
		cr.set_source_rgb(1, 1, 1)
		cr.paint()

		# Draw edges under nodes
		self._draw_edges(cr)

		# Draw nodes
		for key, node in self.nodes.items():
			self._draw_node(cr, node)

		# Column titles (tiers)
		cr.set_source_rgb(0.25, 0.25, 0.25)
		cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
		cr.set_font_size(13)
		for idx, tier in enumerate(self.tiers_sorted):
			x = MARGIN + idx * (NODE_W + H_SPACING)
			cr.move_to(x, 16)
			cr.show_text(f"Tier {tier}")

		return False

	def _hit_test(self, x: float, y: float) -> Optional[str]:
		for key, node in self.nodes.items():
			nx, ny, w, h = node.rect()
			if nx <= x <= nx + w and ny <= y <= ny + h:
				return key
		return None

	def on_button_press(self, widget, event):
		if event.button == 1:
			key = self._hit_test(event.x, event.y)
			if key:
				self.emit("tech-clicked", key)
				return True
		return False

	def on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip: Gtk.Tooltip):
		key = self._hit_test(x, y)
		if not key:
			return False
		tech = self.nodes[key].tech

		def human(k: str) -> str:
			return self.key_to_name.get(k, k)

		prereq_names = [human(k) for k in tech.prerequisites] or ["—"]
		cats = ", ".join(tech.categories) if tech.categories else "—"

		# Build weight modifiers summary
		wm_lines = []
		for wm in tech.weight_modifiers[:8]:
			if wm.kind in ("factor", "add"):
				wm_lines.append(f"{wm.kind}={wm.value} if {wm.condition}".strip())
			else:
				wm_lines.append(wm.condition.strip())
		if len(tech.weight_modifiers) > 8:
			wm_lines.append("…")

		text = (
				f"{tech.name}\n"
				f"Area: {tech.area} | Tier: {tech.tier}\n"
				f"Cost: {tech.cost or '—'} | Categories: {cats}\n"
				f"Base weight: {tech.weight_base or '—'}\n"
				f"Weight modifiers:\n  - " + "\n  - ".join(wm_lines) + "\n"
																	   f"Prerequisites:\n  - " + "\n  - ".join(prereq_names)
		)
		tooltip.set_text(text)
		return True


class MainWindow(Gtk.Window):
	def __init__(self, techs: Dict[str, Tech], key_to_name: Dict[str, str]):
		super().__init__(title="Stellaris Tech Trees (first version)")
		self.set_default_size(1200, 800)

		nb = Gtk.Notebook()
		self.add(nb)

		# Areas in canonical order
		areas = [("physics", "Physics"), ("society", "Society"), ("engineering", "Engineering")]

		for area_key, area_label in areas:
			area_techs = [t for t in techs.values() if t.area == area_key]
			canvas = TechAreaCanvas(area_key, area_techs, key_to_name)
			scroller = Gtk.ScrolledWindow()
			scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
			scroller.add_with_viewport(canvas)
			nb.append_page(scroller, Gtk.Label(label=area_label))

		self.connect("destroy", Gtk.main_quit)


# --- main --------------------------------------------------------------------

def main():
	base_dir = os.path.abspath(os.path.dirname(__file__))
	data_dir = os.path.join(base_dir, "data")
	common_dir = os.path.join(data_dir, "common")
	loc_dir = os.path.join(data_dir, "localisation")

	if not os.path.isdir(common_dir):
		print(f"ERROR: Not found: {common_dir}", file=sys.stderr)
		sys.exit(1)
	if not os.path.isdir(loc_dir):
		print(f"ERROR: Not found: {loc_dir}", file=sys.stderr)
		sys.exit(1)

	# Load localisation (English by default)
	loc_map = load_localisation(loc_dir, language="english")

	# Parse techs
	parser = ClausewitzTechParser(common_dir, loc_map)
	techs = parser.parse()

	# Build mapping for names of prerequisites too
	key_to_name = {k: (t.name or k) for k, t in techs.items()}
	# Also include description keys if needed later (key_desc), but not required here

	win = MainWindow(techs, key_to_name)
	win.show_all()
	Gtk.main()


if __name__ == "__main__":
	main()
