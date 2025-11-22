import re
from typing import Optional
from .context import GlobalContext
from .types import (
	JobEffect,
	JobEffectProductionAdd,
	JobEffectUpkeepMult,
	Job,
	Resource,
)

class JobEffectParser:
	"""
	Base parser for individual modifier entries.
	Subclasses should override `parse` to return a JobEffect or None.
	"""
	@staticmethod
	def parse_any_job_effect(entry: str, src: str = "") -> Optional[JobEffect]:
		"""
		Iterate through all subclasses and return the first JobEffect that matches.
		Returns None if no parser matches.
		"""
		for parser_cls in JobEffectParser.__subclasses__():
			eff = parser_cls.parse(entry, src)
			if eff is not None:
				return eff
		return None

	@staticmethod
	def parse(entry: str, src: str = "") -> Optional[JobEffect]:
		"""
		Override in subclasses: try to parse the entry and return a JobEffect,
		or return None if the entry does not match.
		"""
		raise NotImplementedError

class JobEffectProductionAddParser(JobEffectParser):
	"""
	Parser for lines like 'planet_researchers_society_research_produces_add = 1'.
	Uses GlobalContext.planet_job_produces_add_re.
	"""
	pattern = GlobalContext.planet_job_produces_add_re

	@staticmethod
	def parse(entry: str, src: str = "") -> Optional[JobEffect]:
		m = JobEffectProductionAddParser.pattern.match(entry)
		if not m:
			return None
		group = m.group("group")
		res_key = m.group("res")
		amount = float(m.group("amount"))

		# Convert plural group to singular job key if needed
		base = group[:-1] if group.endswith("s") else group
		job_key = f"job_{base}"
		try:
			job: Job = GlobalContext.job_get(job_key)
			resource: Resource = GlobalContext.resource_from_key(res_key)
		except Exception:
			return None

		return JobEffectProductionAdd(
			job=job,
			resource=resource,
			amount=amount,
			scope="unk",
			source=src,
			note=""
		)

class JobEffectUpkeepMultParser(JobEffectParser):
	"""
	Parser for lines like 'planet_bureaucrats_upkeep_mult = -0.20'.
	Uses GlobalContext.planet_job_upkeep_mult_re.
	"""
	pattern = GlobalContext.planet_job_upkeep_mult_re

	@staticmethod
	def parse(entry: str, src: str = "") -> Optional[JobEffect]:
		m = JobEffectUpkeepMultParser.pattern.match(entry)
		if not m:
			return None
		group = m.group("group")
		amount = float(m.group("amount"))

		base = group[:-1] if group.endswith("s") else group
		job_key = f"job_{base}"
		try:
			job: Job = GlobalContext.job_get(job_key)
		except Exception:
			return None

		return JobEffectUpkeepMult(
			job=job,
			amount=amount,
			scope="unk",
			source=src,
			note=""
		)
