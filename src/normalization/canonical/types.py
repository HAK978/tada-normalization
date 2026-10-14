"""Building blocks shared by every canonical record (model §2)."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema, model_validator

from .codes import (
    CalculationBasis,
    CheckResult,
    NationalIdType,
    PercentScale,
    QuantityUnit,
    RatePeriod,
    Severity,
)

_DECIMAL_SCHEMA = WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$"})


def _plain(value: Decimal) -> str:
    return format(value, "f")


def _money(value: Decimal) -> str:
    # Pad to cents without ever dropping digits: 2375.0 -> "2375.00", 59.375 stays "59.375".
    if value.as_tuple().exponent > -2:
        value = value.quantize(Decimal("0.01"))
    return format(value, "f")


DecimalText = Annotated[Decimal, PlainSerializer(_plain, return_type=str), _DECIMAL_SCHEMA]
MoneyText = Annotated[Decimal, PlainSerializer(_money, return_type=str), _DECIMAL_SCHEMA]
Raw = str | int | bool | None


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


E = TypeVar("E")


# Set while mapping files are active (normalization.mappings): (source_field, raw) -> canonical value or None.
MAPPING_OVERRIDE: ContextVar[Callable[[str, Raw], str | None] | None] = ContextVar("mapping_override", default=None)


class Coded(Model, Generic[E]):
    """A canonical code plus exactly what the provider sent and where it came from."""

    value: E
    raw: Raw = None
    label: str | None = None
    source_field: str

    @model_validator(mode="after")
    def _apply_mapping_file(self) -> Coded:
        """An UNMAPPED value resolved by an active mapping file (A-65); never otherwise changed."""
        lookup = MAPPING_OVERRIDE.get()
        if lookup is None or str(getattr(self.value, "value", self.value)) != "UNMAPPED":
            return self
        target = lookup(self.source_field, self.raw)
        if target is not None:
            kind = type(self).__pydantic_generic_metadata__["args"]
            enum = kind[0] if kind else str
            try:
                value = target if enum is str else enum(target)
            except ValueError as exc:
                raise ValueError(
                    f"mapping file: {target!r} is not a valid {enum.__name__} for {self.source_field}"
                ) from exc
            object.__setattr__(self, "value", value)
        return self


class Money(Model):
    amount: MoneyText
    currency: str = "USD"
    derived: bool = False
    formula: str | None = None
    source_field: str | None = None


class Rate(Model):
    """An amount that only means something together with the period it covers."""

    amount: DecimalText
    currency: str = "USD"
    per: RatePeriod
    derived: bool = False
    formula: str | None = None
    source_field: str | None = None


class Quantity(Model):
    value: DecimalText
    unit: QuantityUnit
    raw: Raw = None
    derived: bool = False
    formula: str | None = None
    source_field: str | None = None


class Percent(Model):
    """percent is null (and left out of the output) whenever the provider's scale (5 vs 0.05) is not proven (A-29)."""

    percent: DecimalText | None = None
    basis: CalculationBasis = CalculationBasis.UNSPECIFIED
    scale: PercentScale
    raw: Raw = None
    source_field: str | None = None


class DateRange(Model):
    start: date | None = None
    end: date | None = None


class Diagnostic(Model):
    code: str
    severity: Severity
    field: str | None = None
    message: str
    raw: Raw = None


class Source(Model):
    provider: str
    tenant_id: str
    endpoints: list[str] = Field(default_factory=list)
    ids: dict[str, str] = Field(default_factory=dict)


class NationalId(Model):
    type: NationalIdType
    last4: str | None = None
    masked_at_source: bool | None = None
    source_field: str


class TaxIdentifier(Model):
    """A business tax ID (FEIN). Not personal data, so it is kept as returned; masked values stay masked."""

    value: str | None = None
    masked_at_source: bool = False
    source_field: str


class CheckOutcome(Model):
    rule: str
    result: CheckResult
    detail: str


class Record(Model):
    id: str
    source: Source
    provider_extensions: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
