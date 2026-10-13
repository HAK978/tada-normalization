"""UKG Ready code tables. UKG documents its enums without definitions, so a value is mapped only
when UKG labels it (a display_name in a response or a documented sample) or live arithmetic shows
what it means (A-26). Tenant-configured lists (pay types, employee types, earning and deduction
codes) stay UNMAPPED with their names (A-35).

Spec: contracts/ukg-ready/reference-schemas.json, cited by schema index (#/schemas/N), and the
pages under contracts/ukg-ready/reference-docs/.
"""

from normalization.canonical.codes import (
    AccountType,
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
)

# employees/{aid} status (#/schemas/106) is undocumented. Live, "Terminated" appears exactly when
# dates.terminated is set (12 of 12), and "Active" exactly when it isn't (3 of 3) (A-55).
EMPLOYEE_STATUS = {"Active": EmploymentStatus.ACTIVE, "Terminated": EmploymentStatus.TERMINATED}

# national_id_numbers[].type (#/schemas/106 enum); only SSN is named for the US.
NATIONAL_ID_TYPE = {"SSN": NationalIdType.SSN}

# compensation/history amount_period (#/schemas/122). Live, amount / hours per period = hourly_pay
# on all 27 records with an amount (A-56). WEEK and MONTH weren't seen live.
RATE_PERIOD = {
    "HOUR": RatePeriod.HOUR,
    "WEEK": RatePeriod.WEEK,
    "MONTH": RatePeriod.MONTH,
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
DD_ACCOUNT_TYPE = {"CHECKING": AccountType.CHECKING, "SAVINGS": AccountType.SAVINGS}
# deposits[].type: reserves a paper ("live") check instead of naming a bank account.
RESERVE_LIVE_CHECK = "RESERVE_LIVE_CHECK"

# payrolls status (#/schemas/360). OPEN -> CLOSED -> FINALIZED are the documented close and
# finalize steps ("Performs the finalize process on the specified payrolls if closed"); the
# *_FAILED values name a failed step. NEW stays UNMAPPED (A-57).
RUN_STATUS = {
    "OPEN": PayrollRunStatus.OPEN,
    "CLOSED": PayrollRunStatus.CLOSED,
    "SUBMITTED": PayrollRunStatus.SUBMITTED,
    "FINALIZED": PayrollRunStatus.COMPLETED,
    "OPEN_FAILED": PayrollRunStatus.FAILED,
    "CLOSE_FAILED": PayrollRunStatus.FAILED,
    "ROLLBACK_FAILED": PayrollRunStatus.FAILED,
    "FINALIZE_FAILED": PayrollRunStatus.FAILED,
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
