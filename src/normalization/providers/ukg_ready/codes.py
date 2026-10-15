"""UKG Ready code tables. UKG documents its enums without definitions, so a value is mapped only
when UKG labels it (a display_name in a response or a documented sample) or live arithmetic shows
what it means (A-26). Tenant-configured lists (pay types, employee types, earning and deduction
codes) stay UNMAPPED with their names (A-35).

Spec: contracts/ukg-ready/reference-schemas.json, cited by schema index (#/schemas/N), and the
pages under contracts/ukg-ready/reference-docs/.
"""

from normalization.canonical.codes import (
    AccountType,
    ContactRole,
    DepositMethod,
    EarningKind,
    EmploymentStatus,
    NationalIdType,
    PayFrequency,
    PaymentKind,
    PayrollRunStatus,
    PayrollRunType,
    PayStatementType,
    RatePeriod,
    TaxType,
)

# employees/{aid} status (#/schemas/106) is undocumented. Live, "Terminated" appears exactly when
# dates.terminated is set (12 of 12), and "Active" exactly when it isn't (3 of 3) (A-55).
EMPLOYEE_STATUS = {"Active": EmploymentStatus.ACTIVE, "Terminated": EmploymentStatus.TERMINATED}

# employees/{aid}/contacts: the flags behind the documented contact_type filter, "Valid values: EMERGENCY,
# DEPENDENT, BENEFICIARY ... Used to fetch account contacts filtered by contact type" (A-77).
CONTACT_ROLES = (
    ("emergency", ContactRole.EMERGENCY),
    ("dependent", ContactRole.DEPENDENT),
    ("beneficiary", ContactRole.BENEFICIARY),
)

# employees/{aid}/demographics gender, citizenship and ethnicity are documented enums without definitions, so
# there is deliberately no table: they stay UNMAPPED with the value as sent (A-26, A-79).

# national_id_numbers[].type (#/schemas/106 enum); only SSN is named for the US.
NATIONAL_ID_TYPE = {"SSN": NationalIdType.SSN}

# compensation/history amount_period (#/schemas/122). Live, amount / hours per period = hourly_pay on every
# record with an amount, for each of these three periods (A-56). WEEK and MONTH are documented without a
# definition and never seen live, so they stay UNMAPPED (A-26).
RATE_PERIOD = {
    "HOUR": RatePeriod.HOUR,
    "YEAR": RatePeriod.YEAR,
    "PAY_PERIOD": RatePeriod.PAY_PERIOD,
}

# num_pp_in_year: a count of pay periods; each count below is that frequency's definition (A-56).
FREQUENCY_BY_COUNT = {
    52: PayFrequency.WEEKLY,
    26: PayFrequency.BIWEEKLY,
    24: PayFrequency.SEMIMONTHLY,
    12: PayFrequency.MONTHLY,
    4: PayFrequency.QUARTERLY,
    2: PayFrequency.SEMIANNUALLY,
    1: PayFrequency.ANNUALLY,
}

# direct-deposits calc_method.type (#/schemas/137), mapped only where UKG labels it (A-26):
# FULL "Entire/Remainder" (live), FLAT_AMOUNT "Flat Amount" and GROSS_EARNING "% Of Gross
# Earnings" (documented samples). NET_PAY and DIRECT_DEPOSIT_PER_OF_REMAINDER have no label.
DD_METHOD = {
    "FULL": DepositMethod.REMAINDER,
    "FLAT_AMOUNT": DepositMethod.FIXED_AMOUNT,
    "GROSS_EARNING": DepositMethod.PERCENT_OF_GROSS,
}
# direct-deposits account_type (CHECKING, SAVINGS) and type (DIRECT_DEPOSIT, RESERVE_LIVE_CHECK) are
# documented enums with no definition, and no response labels them, so there is deliberately no table: they
# stay UNMAPPED with the value as sent until a mapping file confirms them (A-26, A-86).
DD_ACCOUNT_TYPE: dict[str, AccountType] = {}
# A RESERVE_LIVE_CHECK row names no bank account (documented sample), so its type stands in for one.
RESERVE_LIVE_CHECK = "RESERVE_LIVE_CHECK"

# payrolls status (#/schemas/360). The documented payroll actions name these states: "Performs closing
# process", "Performs the submit process on the specified payrolls if closed", "Performs the finalize
# process on the specified payrolls if closed", "Performs reopening process" (live: every payroll is OPEN).
# NEW and the *_FAILED values have no definition anywhere, so they stay UNMAPPED (A-57).
RUN_STATUS = {
    "OPEN": PayrollRunStatus.OPEN,
    "CLOSED": PayrollRunStatus.CLOSED,
    "SUBMITTED": PayrollRunStatus.SUBMITTED,
    "FINALIZED": PayrollRunStatus.COMPLETED,
}

# lookup/payroll-types is "the list of supported payroll types". The documented sample and the live
# tenant list the same names under different IDs, so names are matched, never IDs (A-57).
RUN_TYPE = {
    "Regular": PayrollRunType.REGULAR,
    "Void": PayrollRunType.VOID,
    "Correction": PayrollRunType.CORRECTION,
    "Historical": PayrollRunType.HISTORICAL_IMPORT,
}

# lookup/pay-statement-types names from the documented sample of "supported pay statement types".
# The live tenant also has names like "Comm" and "Regular 2", so only these exact names map (A-57).
STATEMENT_TYPE = {
    "Regular": PayStatementType.REGULAR,
    "Manual": PayStatementType.MANUAL,
    "Historical": PayStatementType.HISTORICAL_IMPORT,
}

# pay-statements earnings[].type_name: UKG's own line classification, "<kind> (<modifiers>)" (A-58).
# Live, gross - fringe - employee taxes - deductions = check + direct deposit on 22 of 22
# statements, so "Earning" lines are paid in cash and "Fringe" ones are not.
EARNING_TYPE = {"Earning": EarningKind.EARNINGS, "Reimbursement": EarningKind.REIMBURSEMENT}
FRINGE = "Fringe"
# Modifiers seen live or in documented samples. An unknown one could change the meaning, so a line
# carrying one stays UNMAPPED.
KNOWN_MODIFIERS = frozenset({"Auto", "Auto Reduce", "Manual", "Fringe", "Neg Ded"})

# payments[].type_name. "Fringe" rows equal the fringe earnings (22 of 22 live): they balance the
# non-cash pay and pay nothing, so they are not payments (A-58).
PAYMENT_TYPE = {"Check": PaymentKind.CHECK, "Direct Deposit": PaymentKind.DIRECT_DEPOSIT}
FRINGE_PAYMENT = "Fringe"

# taxes[].company_tax.code (A-68). lookup/tax-codes, "the list of supported tax codes", documents
# FIT "Federal Income Tax", FUTA "Federal Unemployment Tax", FICA "OASDI", MEDI "Medicare" and
# "Additional Medicare". Live, "Social Security" and "Medicare" are named so and, like FICA and MEDI,
# withhold exactly 6.2% and 1.45% of subject wages on every line with an amount.
TAX_CODE = {
    "FIT": TaxType.FEDERAL_INCOME,
    "FICA": TaxType.SOCIAL_SECURITY,
    "Social Security": TaxType.SOCIAL_SECURITY,
    "MEDI": TaxType.MEDICARE,
    "Medicare": TaxType.MEDICARE,
    "Additional Medicare": TaxType.ADDITIONAL_MEDICARE,
    "FUTA": TaxType.FEDERAL_UNEMPLOYMENT,
}
# State taxes are coded "<tax>:<state>[:<n>]" live (SIT:WI, SIT:WI:2, SUTA:WI:2). SUTA is named "ER SUTA
# <state>" and is employer-only. SIT is named after the state only; its subject wage equals FIT's on 62
# of 63 live statements, including all 28 where FIT's differs from Social Security's, so it is taxed
# on the income-tax wage base (A-68). Other prefixes (SUTA_SC, ...) stay UNMAPPED.
STATE_TAX_PREFIX = {"SIT": TaxType.STATE_INCOME, "SUTA": TaxType.STATE_UNEMPLOYMENT}

# Failed requests that mean "nothing here" (A-70). None so far: live, cost-center tree 1 answers HTTP 400
# "Cost Center not used.", yet 8 employees are assigned cost centers in it, so that answer is unavailable
# data, not an empty tree (A-75).
EMPTY_MESSAGES: dict[str, tuple[str, ...]] = {}
