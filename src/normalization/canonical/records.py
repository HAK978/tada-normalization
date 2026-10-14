"""The six canonical record types (model §3 to §8)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from .codes import (
    AccountType,
    AddressType,
    CalculationBasis,
    CalculationMethod,
    Citizenship,
    CompanyStatus,
    DeductionCategory,
    DepositMethod,
    DepositPurpose,
    DepositStatus,
    EarningCategory,
    EarningKind,
    ElectionStatus,
    EmailType,
    EmployerKind,
    EmploymentStatus,
    EmploymentType,
    FundingParty,
    Gender,
    IdentifierType,
    LimitBasis,
    MaritalStatus,
    PayFrequency,
    PayKindScope,
    PaymentKind,
    PayrollRunStatus,
    PayrollRunType,
    PayStatementType,
    PayType,
    PhoneType,
    Rounding,
    ServiceArrangement,
    TaxPaidBy,
    TaxTreatment,
    TaxType,
    WorkerClassification,
    YesNoDeclined,
)
from .types import (
    CheckOutcome,
    Coded,
    DateRange,
    Model,
    Money,
    NationalId,
    Percent,
    Quantity,
    Rate,
    Raw,
    Record,
    TaxIdentifier,
)

# ---------------------------------------------------------------- shared parts


class Address(Model):
    type: AddressType
    line1: str | None = None
    line2: str | None = None
    line3: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Phone(Model):
    type: PhoneType
    number: str
    extension: str | None = None


class Email(Model):
    type: EmailType
    address: str


class OrgUnit(Model):
    code: str
    name: str | None = None


class FrequencyInfo(Model):
    frequency: Coded[PayFrequency]
    periods_per_year: int | None = None


# ---------------------------------------------------------------- company


class EmployerRef(Model):
    kind: EmployerKind
    provider_id: str | None = None
    name: str | None = None
    tax_id: TaxIdentifier | None = None


class PayGroup(Model):
    code: str
    name: str | None = None
    frequency: FrequencyInfo | None = None


class Company(Record):
    name: str | None = None
    legal_name: str | None = None
    parent: OrgUnit | None = None
    status: Coded[CompanyStatus] | None = None
    own_tax_id: TaxIdentifier | None = None
    service_arrangement: Coded[ServiceArrangement] | None = None
    employers: list[EmployerRef] = Field(default_factory=list)
    pay_groups: list[PayGroup] = Field(default_factory=list)
    addresses: list[Address] = Field(default_factory=list)
    phones: list[Phone] = Field(default_factory=list)
    emails: list[Email] = Field(default_factory=list)


# ---------------------------------------------------------------- employee


class Identifier(Model):
    type: IdentifierType
    value: str
    source_field: str


class PersonName(Model):
    first: str | None = None
    middle: str | None = None
    last: str | None = None
    preferred: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    nickname: str | None = None


class EmergencyContact(Model):
    name: str | None = None
    relationship: str | None = None
    contact_type: str | None = None
    contact_info: str | None = None


class Personal(Model):
    birth_date: date | None = None
    gender: Coded[Gender] | None = None
    marital_status: Coded[MaritalStatus] | None = None
    ethnicity: Coded[str] | None = None
    veteran: Coded[YesNoDeclined] | None = None
    disabled: Coded[YesNoDeclined] | None = None
    citizenship: Coded[Citizenship] | None = None
    preferred_language: str | None = None
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list)


class Employment(Model):
    status: Coded[EmploymentStatus] | None = None
    status_date: date | None = None
    employment_type: Coded[EmploymentType] | None = None
    worker_classification: Coded[WorkerClassification] | None = None
    original_hire_date: date | None = None
    hire_date: date | None = None
    rehire_date: date | None = None
    start_date: date | None = None
    seniority_date: date | None = None
    termination_date: date | None = None
    last_worked_date: date | None = None
    termination_reason: Coded[str] | None = None
    flsa_exempt: bool | None = None
    employer_ids: list[str] = Field(default_factory=list)


class Job(Model):
    title: str | None = None
    job_code: str | None = None
    department: OrgUnit | None = None
    division: OrgUnit | None = None
    location: OrgUnit | None = None
    manager_employee_id: str | None = None
    supervisor_employee_id: str | None = None
    union: OrgUnit | None = None
    pay_group: str | None = None


class CompensationChange(Model):
    source_id: str | None = None
    effective_date: date | None = None
    pay_type: Coded[PayType] | None = None
    rates: list[Rate] = Field(default_factory=list)
    annual_pay: Money | None = None
    standard_hours: Quantity | None = None
    reason: str | None = None


class Compensation(Model):
    pay_type: Coded[PayType] | None = None
    pay_frequency: FrequencyInfo | None = None
    rates: list[Rate] = Field(default_factory=list)
    annual_pay: Money | None = None
    standard_hours: Quantity | None = None
    standard_hours_per: str | None = None
    effective_date: date | None = None
    history: list[CompensationChange] = Field(default_factory=list)


class Employee(Record):
    company_id: str
    legal_entity_id: str | None = None
    identifiers: list[Identifier] = Field(default_factory=list)
    national_id: NationalId | None = None
    name: PersonName = Field(default_factory=PersonName)
    personal: Personal = Field(default_factory=Personal)
    addresses: list[Address] = Field(default_factory=list)
    phones: list[Phone] = Field(default_factory=list)
    emails: list[Email] = Field(default_factory=list)
    employment: Employment = Field(default_factory=Employment)
    job: Job = Field(default_factory=Job)
    compensation: Compensation = Field(default_factory=Compensation)


# ---------------------------------------------------------------- direct deposit


class BankAccount(Model):
    type: Coded[AccountType]
    routing_number: str | None = None
    routing_type: str | None = None
    account_last4: str | None = None
    masked_at_source: bool | None = None
    bank_name: str | None = None


class Prenote(Model):
    status: Coded[str] | None = None
    sent_date: date | None = None
    expiration_date: date | None = None


class DirectDeposit(Record):
    employee_id: str
    company_id: str
    purpose: DepositPurpose
    funding: Coded[FundingParty] | None = None
    account: BankAccount
    method: Coded[DepositMethod]
    amount: Money | None = None
    percent: Percent | None = None
    limit: Money | None = None
    sequence: int | None = None
    is_remainder: bool
    status: Coded[DepositStatus] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    frequency: Coded[str] | None = None
    applies_to_pay_types: list[Coded[PayKindScope]] = Field(default_factory=list)
    prenote: Prenote | None = None
    currency: str | None = None


# ---------------------------------------------------------------- deduction setup


class Calculation(Model):
    method: Coded[CalculationMethod]
    basis: CalculationBasis = CalculationBasis.UNSPECIFIED
    amount: Money | None = None
    percent: Percent | None = None
    rate: Rate | None = None
    rounding: Rounding | None = None


class DeductionLimits(Model):
    per_period: Money | None = None
    maximum: Money | None = None
    maximum_basis: Coded[LimitBasis] | None = None


class EmployerMatch(Model):
    method: Coded[CalculationMethod]
    amount: Money | None = None
    percent: Percent | None = None
    description: str | None = None


class LoanDetails(Model):
    principal: Money | None = None
    payback_amount: Money | None = None
    paid_to_date: Money | None = None
    payment_amount: Money | None = None
    payment_frequency: Coded[str] | None = None
    loan_date: date | None = None
    reason: str | None = None


class GarnishmentDetails(Model):
    case_number: str | None = None
    garnishment_type: Coded[str] | None = None
    payee: str | None = None
    issuing_state: str | None = None
    arrears_balance: Money | None = None
    remaining_balance: Money | None = None
    fee: Money | None = None


class DeductionElection(Record):
    employee_id: str
    company_id: str
    code: str
    label: str | None = None
    category: Coded[DeductionCategory]
    tax_treatment: TaxTreatment = TaxTreatment.UNSPECIFIED
    catch_up: bool | None = None
    calculation: Calculation | None = None
    limits: DeductionLimits | None = None
    status: Coded[ElectionStatus] | None = None
    frequency: Coded[str] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    employer_match: EmployerMatch | None = None
    arrears_tracking: bool | None = None
    mandatory: bool | None = None
    benefit_plan_id: str | None = None
    loan_or_garnishment_id: str | None = None
    loan: LoanDetails | None = None
    garnishment: GarnishmentDetails | None = None


# ---------------------------------------------------------------- payroll


class RunPayGroup(Model):
    pay_group: str
    period: DateRange
    weeks_worked: Raw = None
    deduction_period: str | None = None


class PayrollRun(Record):
    company_id: str
    pay_date: date | None = None
    processed_date: date | None = None
    description: str | None = None
    type: Coded[PayrollRunType]
    status: Coded[PayrollRunStatus] | None = None
    pay_groups: list[RunPayGroup] = Field(default_factory=list)
    # For providers that give one period per run rather than per pay group (UKG).
    period: DateRange | None = None
    # The legal entity the run is for, when the provider says (a UKG EIN).
    legal_entity_id: str | None = None


class EarningLine(Model):
    code: str | None = None
    label: str | None = None
    kind: Coded[EarningKind]
    # What the pay is for (A-67). Set on earnings lines only: reimbursement, fringe, tips and memo
    # lines are already specific. UNMAPPED with the earning code as raw when the provider doesn't say.
    category: Coded[EarningCategory] | None = None
    # Whether the provider counts this line in gross wages (Prism: all lines, A-32; isolved: not memo, A-28).
    in_gross: bool | None = None
    quantity: Quantity | None = None
    hours_worked: Quantity | None = None
    rate: Rate | None = None
    amount: Money
    period: DateRange | None = None
    allocation: dict[str, str] = Field(default_factory=dict)
    source_field: str


class TaxLine(Model):
    code: str | None = None
    label: str | None = None
    type: Coded[TaxType] | None = None  # A-68
    state: str | None = None  # USPS code, for a state-level type when the provider's code or label names it
    paid_by: TaxPaidBy
    amount: Money
    taxable_wages: Money | None = None
    source_field: str


class DeductionLine(Model):
    code: str | None = None
    external_id: str | None = None
    label: str | None = None
    category: Coded[DeductionCategory] | None = None
    tax_treatment: TaxTreatment = TaxTreatment.UNSPECIFIED
    employee_amount: Money | None = None
    employer_amount: Money | None = None
    source_field: str


class ContributionLine(Model):
    code: str | None = None
    label: str | None = None
    amount: Money
    source_field: str


class BenefitDetail(Model):
    """Informational premium detail; never added into totals (it overlaps deduction lines)."""

    plan: str | None = None
    coverage_period: str | None = None
    premium: Money | None = None
    premium_cost: Money | None = None
    employee_contribution: Money | None = None
    employee_deduction: Money | None = None
    employer_contribution: Money | None = None
    source_field: str


class RetirementSummary(Model):
    plan: str | None = None
    base_earnings: Money | None = None
    amounts: dict[str, Money] = Field(default_factory=dict)


class PaymentLine(Model):
    kind: Coded[PaymentKind]
    amount: Money
    routing_number: str | None = None
    account_last4: str | None = None
    masked_at_source: bool | None = None
    status: Raw = None
    source_field: str


class PayStatementTotals(Model):
    # The part of gross actually paid: gross wages minus non-cash earnings (A-54).
    gross_pay: Money | None = None
    # Every earning counted in gross, non-cash ones included (A-54).
    gross_wages: Money | None = None
    net_pay: Money | None = None
    employee_taxes: Money | None = None
    employer_taxes: Money | None = None
    deductions: Money | None = None
    employer_contributions: Money | None = None


class PayStatement(Record):
    company_id: str
    employee_id: str
    payroll_run_id: str | None = None
    pay_date: date | None = None
    period: DateRange = Field(default_factory=DateRange)
    check_number: str | None = None
    type: Coded[PayStatementType]
    status: Coded[str] | None = None
    voided: bool = False
    void_date: date | None = None
    totals: PayStatementTotals = Field(default_factory=PayStatementTotals)
    earnings: list[EarningLine] = Field(default_factory=list)
    taxes: list[TaxLine] = Field(default_factory=list)
    deductions: list[DeductionLine] = Field(default_factory=list)
    employer_contributions: list[ContributionLine] = Field(default_factory=list)
    benefit_details: list[BenefitDetail] = Field(default_factory=list)
    retirement: RetirementSummary | None = None
    payments: list[PaymentLine] = Field(default_factory=list)
    checks: list[CheckOutcome] = Field(default_factory=list)


RECORD_TYPES: dict[str, type[Record]] = {
    "companies": Company,
    "employees": Employee,
    "direct_deposits": DirectDeposit,
    "deduction_elections": DeductionElection,
    "payroll_runs": PayrollRun,
    "pay_statements": PayStatement,
}


def dump(record: Record) -> dict[str, Any]:
    """JSON-ready dict: decimals as strings, dates as ISO, unset optional parts omitted."""
    return record.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
