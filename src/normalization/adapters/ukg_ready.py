"""UKG Ready adapter: candidate must discover and implement all source mappings."""
from typing import Any, Dict


def normalize(entity: str, response: Any, reference: Dict[str, Any]) -> Any:
    """Return the candidate-designed JSON-serializable canonical result.

    Do not infer units, endpoint shapes, or enum meanings from this stub.
    Preserve documented source semantics and define diagnostics in your design.
    """
    raise NotImplementedError("Implement UKG Ready company/employee/payroll mappings from approved evidence.")
