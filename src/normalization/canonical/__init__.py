"""The canonical model: one shape for company, employee, deposit, deduction and payroll data."""

from .records import RECORD_TYPES, dump

__all__ = ["RECORD_TYPES", "dump"]
