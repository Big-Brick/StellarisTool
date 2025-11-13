from dataclasses import dataclass

@dataclass
class Job:
	key: str    # e.g. "job_physicist"
	name: str   # localized display name, e.g. "Physicist"