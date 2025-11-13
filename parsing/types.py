from dataclasses import dataclass

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
class TriggeredCountryModifierBlock(BlockBase):
	@classmethod
	def keyword(cls) -> str:
		return "triggered_country_modifier"


@dataclass
class TriggeredPlanetModifierBlock(BlockBase):
	@classmethod
	def keyword(cls) -> str:
		return "triggered_planet_modifier"

