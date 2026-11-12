"""Repository layer.

Repos are the ONLY write path to persistent data. Conventions:
- Each mutating method commits and refreshes.
- Enum fields are coerced through Python enums; unknown values raise ValueError
  (with all valid options listed) so malformed data can never be silently stored.
- Domain rule violations raise ValueError with explicit messages.
- Append-only tables (assessments, outcomes, sprint visits/signups/signals/
  verdicts) deliberately expose no update or delete path for their facts.
"""

from .assessments import AssessmentRepository
from .cases import CaseRepository
from .evidence import EvidenceRepository
from .experiments import ExperimentRepository
from .hypotheses import HypothesisRepository
from .runs import RunRepository
from .scans import ScanRepository
from .sprints import SprintRepository
from .uploads import UploadRepository
from .users import UserRepository

__all__ = [
    "AssessmentRepository",
    "CaseRepository",
    "EvidenceRepository",
    "ExperimentRepository",
    "HypothesisRepository",
    "RunRepository",
    "ScanRepository",
    "SprintRepository",
    "UploadRepository",
    "UserRepository",
]
