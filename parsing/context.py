from dataclasses import dataclass, field
from typing import Dict, Type

import re

@dataclass(frozen=True)
class Resource:
	key: str
	name: str  # human-readable (can use loc if you want later)

@dataclass(frozen=True)
class EnergyResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="energy", name="Energy")


@dataclass(frozen=True)
class MineralsResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="minerals", name="Minerals")


@dataclass(frozen=True)
class FoodResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="food", name="Food")


@dataclass(frozen=True)
class AlloysResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="alloys", name="Alloys")


@dataclass(frozen=True)
class ConsumerGoodsResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="consumer_goods", name="Consumer Goods")

@dataclass(frozen=True)
class UnityResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="unity", name="Unity")


@dataclass(frozen=True)
class TradeValueResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="trade_value", name="Trade Value")


@dataclass(frozen=True)
class PhysicsResearchResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="physics_research", name="Physics Research")


@dataclass(frozen=True)
class SocietyResearchResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="society_research", name="Society Research")


@dataclass(frozen=True)
class EngineeringResearchResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="engineering_research", name="Engineering Research")


@dataclass(frozen=True)
class ExoticGasesResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="exotic_gases", name="Exotic Gases")


@dataclass(frozen=True)
class VolatileMotesResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="volatile_motes", name="Volatile Motes")


@dataclass(frozen=True)
class RareCrystalsResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="rare_crystals", name="Rare Crystals")


@dataclass(frozen=True)
class DarkMatterResource(Resource):  # sr_dark_matter
	def __init__(self) -> None:
		super().__init__(key="sr_dark_matter", name="Dark Matter")


@dataclass(frozen=True)
class LivingMetalResource(Resource):  # sr_living_metal
	def __init__(self) -> None:
		super().__init__(key="sr_living_metal", name="Living Metal")


@dataclass(frozen=True)
class ZroResource(Resource):  # sr_zro
	def __init__(self) -> None:
		super().__init__(key="sr_zro", name="Zro")


@dataclass(frozen=True)
class NanitesResource(Resource):
	def __init__(self) -> None:
		super().__init__(key="nanites", name="Nanites")

_RESOURCE_CLASS_MAP: Dict[str, Type[Resource]] = {
	"energy": EnergyResource,
	"minerals": MineralsResource,
	"food": FoodResource,
	"alloys": AlloysResource,
	"consumer_goods": ConsumerGoodsResource,
	"unity": UnityResource,
	"trade_value": TradeValueResource,

	"physics_research": PhysicsResearchResource,
	"society_research": SocietyResearchResource,
	"engineering_research": EngineeringResearchResource,

	"exotic_gases": ExoticGasesResource,
	"volatile_motes": VolatileMotesResource,
	"rare_crystals": RareCrystalsResource,

	"sr_dark_matter": DarkMatterResource,
	"sr_living_metal": LivingMetalResource,
	"sr_zro": ZroResource,

	"nanites": NanitesResource,
	# extend as needed when the parser hits new resources
}

@dataclass
class Job:
	key: str	# e.g. "job_physicist"
	name: str   # localized display name, e.g. "Physicist"

@dataclass
class GlobalContext:
	job_map: Dict[str, Job] = field(default_factory=dict)
	loc: Dict[str, str] = field(default_factory=dict)
	planet_job_produces_add_re: re.Pattern[str] = re.compile(
		r'\bplanet_(?P<group>[A-Za-z0-9_]+)_(?P<res>[A-Za-z0-9_]+)_produces_add\s*=\s*(?P<amount>[-+]?\d+(?:\.\d+)?)'
	)
	jobs_workforce_mult_re: re.Pattern[str] = re.compile(
		r'\b([a-z_]+)_jobs_bonus_workforce_mult\s*=\s*([+-]?\d+(?:\.\d+)?)'
	)

	@classmethod
	def set_global_context(cls, job_map: Dict[str, Job], loc: Dict[str, str]) -> None:
		cls.job_map = job_map
		cls.loc = loc

	@classmethod
	def loc_get(cls, key: str) -> str:
		if not cls.job_map or not cls.loc:
			raise RuntimeError("GlobalContext not initialised; call set_global_context(...) first")
		return cls.loc.get(key, key)

	@classmethod
	def job_get(cls, key: str) -> Job:
		if not cls.job_map or not cls.loc:
			raise RuntimeError("GlobalContext not initialised; call set_global_context(...) first")
		if key not in cls.job_map:
			raise UnknowJobError(key)
		return cls.job_map[key]

	@classmethod
	def resource_from_key(cls, key: str) -> "Resource":
		try:
			res_cls = _RESOURCE_CLASS_MAP[key]
		except KeyError:
			raise UnknowResourceError(key)
		return res_cls()

class UnknowJobError(KeyError):
	def __init__(self, key: str):
		super().__init__(f"Unknow job: {key}")

class UnknowResourceError(KeyError):
	def __init__(self, key: str):
		super().__init__(f"Unknow resource: {key}")
