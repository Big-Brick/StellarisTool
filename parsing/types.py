from dataclasses import dataclass, field
from typing import Dict, List

from .context import Job, Resource

@dataclass
class JobEffect:
	job: Job
	kind: str					 # "count", "produces_mult", "upkeep_mult"
	value: str					# as string (keep constants/decimals intact)
	scope: str					# "country" (typical civic modifiers)
	source: str				   # file base (for reference)
	note: str				# optional short note / path inside civic

@dataclass(init=False)
class JobEffectProductionAdd(JobEffect):
	"""
	Typed version of 'job produces ADD something'.

	New fields:
	- resource: Resource	 (strongly typed resource)
	- amount:   int		  (numeric amount)

	But we ALSO keep the base JobEffect fields in sync so existing code keeps working:
	- job_key / job_name / kind / value / src / note
	"""
	resource: Resource
	amount: float

	def __init__(self, job: Job, resource: Resource, amount: float, scope: str, source: str, note: str) -> None:
		self.resource = resource
		self.amount = int(amount)

		# keep old API consistent
		super().__init__(
			job = job,
			kind="produces_add",
			value=str(self.amount),  # legacy string field
			scope=scope,
			source=source,
			note=note,
		)

@dataclass(init=False)
class JobEffectUpkeepMult(JobEffect):
	"""
	Typed version of 'job upkeep multiplier'.
	Stores the numeric multiplier as a float while keeping the base fields in sync.
	"""
	amount: float

	def __init__(self, job: Job, amount: float, scope: str, source: str, note: str) -> None:
		self.amount = float(amount)
		super().__init__(
			job=job,
			kind="upkeep_mult",
			value=str(self.amount),  # legacy string field
			scope=scope,
			source=source,
			note=note,
		)

@dataclass
class CivicJobEffects:
	civic_key: str
	civic_name: str
	effects: List[JobEffect] = field(default_factory=list)

# Base block type for "X = { ... }" style chunks
@dataclass
class BlockBase:
	body: List[str]
	raw_text: str

	@classmethod
	def keyword(cls) -> str:
		"""
		Name of the key in 'keyword = { ... }'.
		Must be overridden by subclasses.
		"""
		raise NotImplementedError

@dataclass
class ModifierBlock(BlockBase):
	@classmethod
	def keyword(cls) -> str:
		return "modifier"

@dataclass
class JobModifierBlock(ModifierBlock):
	modifiers: List[JobEffect] = field(default_factory=list)

	def to_job_effects(self) -> List[JobEffect]:
		return self.modifiers

@dataclass
class TriggeredCountryModifierBlock(BlockBase):
	@classmethod
	def keyword(cls) -> str:
		return "triggered_country_modifier"


@dataclass
class TriggeredPlanetModifierBlock(BlockBase):
	@classmethod
	def keyword(cls) -> str:
		return "triggered_planet_modifier"

