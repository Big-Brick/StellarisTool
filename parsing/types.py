from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class JobEffect:
	job_key: str				  # e.g., job_researcher
	job_name: str				 # localized single-name (e.g., Researcher)
	kind: str					 # "count", "produces_mult", "upkeep_mult"
	value: str					# as string (keep constants/decimals intact)
	scope: str					# "country" (typical civic modifiers)
	source: str				   # file base (for reference)
	note: str = ""				# optional short note / path inside civic

@dataclass
class CivicJobEffects:
	civic_key: str
	civic_name: str
	effects: List[JobEffect] = field(default_factory=list)

@dataclass
class Job:
	key: str    # e.g. "job_physicist"
	name: str   # localized display name, e.g. "Physicist"

# Base block type for "X = { ... }" style chunks
@dataclass
class BlockBase:
	body: str      # inner text inside braces: everything between '{' and '}'
	raw_text: str  # full text of the block, e.g. 'modifier = { ... }'

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
class TypedModifierBlock(ModifierBlock):
	"""
	Base for strongly-typed modifier blocks.
	Subclasses should parse `body` in __post_init__ and implement to_job_effects().
	"""

	def to_job_effects(
		self,
		jobs: Dict[str, Job],
		src: str,
		context: str,
	) -> List[JobEffect]:
		"""
		Convert this modifier into JobEffect list.
		Must be overridden in subclasses.
		"""
		raise NotImplementedError

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

