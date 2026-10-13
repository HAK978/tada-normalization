"""PrismHR code tables, each keyed to one exact source field.

Evidence is the field description in contracts/prismhr/openapi/prismhr-2025.09.openapi.json
(cited as #/components/schemas/<Schema>/properties/<field>) unless an ASSUMPTIONS.md entry is
named. Codes outside a table become UNMAPPED with a diagnostic.
"""

from normalization.canonical.codes import (
    AccountType,
    CalculationBasis as B,
    CalculationMethod as M,
    Citizenship,
    CompanyStatus,
    DeductionCategory as Cat,
    DepositMethod,
    DepositStatus,
    EarningKind,
    ElectionStatus,
    EmploymentStatus,
    EmploymentType,
    FundingParty,
    Gender,
    LimitBasis,
    MaritalStatus,
    PayFrequency,
    PayKindScope,
    PayrollRunStatus,
    PayrollRunType,
    PayStatementType,
    PayType,
    QuantityUnit,
    RatePeriod,
    Rounding,
    ServiceArrangement,
    TaxTreatment as T,
    YesNoDeclined,
)

# ClientMaster/statusClass
COMPANY_STATUS = {
    "A": CompanyStatus.ACTIVE,
    "P": CompanyStatus.PENDING,
    "I": CompanyStatus.INACTIVE,
    "C": CompanyStatus.TERMINATING,
    "T": CompanyStatus.TERMINATED,
}

# ClientMaster/serviceType
SERVICE_TYPE = {
    "PEO": ServiceArrangement.PEO,
    "ASO": ServiceArrangement.ASO,
    "PAY": ServiceArrangement.PAYROLL_ONLY,
    "ASA": ServiceArrangement.ASO_ALT_BILLING,
    "COR": ServiceArrangement.CORPORATE_PAYROLL,
    "HRN": ServiceArrangement.HR_ONLY,
}

# Client/statusClass ("'A' (active), 'L' (on leave), or 'T' (terminated)")
STATUS_CLASS = {"A": EmploymentStatus.ACTIVE, "L": EmploymentStatus.ON_LEAVE, "T": EmploymentStatus.TERMINATED}

# Client/typeClass: values documented by the getEmployeeList typeClass filter, "(F)ull-time or (P)art-time"
TYPE_CLASS = {"F": EmploymentType.FULL_TIME, "P": EmploymentType.PART_TIME}

# Compensation/payMethod
PAY_METHOD = {"S": PayType.SALARY, "H": PayType.HOURLY, "C": PayType.COMMISSION, "D": PayType.DRIVER}

# Compensation/payPeriod uses the pay-period codes of ClientPayrollSchedule/payPeriodDesc
PAY_PERIOD = {
    "D": (PayFrequency.DAILY, None),
    "W": (PayFrequency.WEEKLY, 52),
    "B": (PayFrequency.BIWEEKLY, 26),
    "S": (PayFrequency.SEMIMONTHLY, 24),
    "M": (PayFrequency.MONTHLY, 12),
}

# Compensation/hourlyPayPeriod documents H/W/B/S/M/Y. "A" is undocumented here but is
# documented as "annually" in PayRate/payPeriod and matches annualPay on 18/18 live records (A-19).
HOURLY_PAY_PERIOD = {
    "H": RatePeriod.HOUR,
    "W": RatePeriod.WEEK,
    "B": RatePeriod.BIWEEK,
    "S": RatePeriod.SEMIMONTH,
    "M": RatePeriod.MONTH,
    "Y": RatePeriod.YEAR,
    "A": RatePeriod.YEAR,
}
UNDOCUMENTED_HOURLY_PAY_PERIOD = {"A"}

# PayRate/payPeriod ("W, B, S, M, A (annually), or H")
PAY_RATE_PERIOD = {
    "W": RatePeriod.WEEK,
    "B": RatePeriod.BIWEEK,
    "S": RatePeriod.SEMIMONTH,
    "M": RatePeriod.MONTH,
    "A": RatePeriod.YEAR,
    "H": RatePeriod.HOUR,
}

# Person/gender lists "M, F, X or D"; only M and F carry an unambiguous meaning (A-44).
GENDER = {"M": Gender.MALE, "F": Gender.FEMALE}

# Person/maritalStatus
MARITAL = {
    "S": MaritalStatus.SINGLE,
    "M": MaritalStatus.MARRIED,
    "D": MaritalStatus.DIVORCED,
    "W": MaritalStatus.WIDOWED,
    "C": MaritalStatus.CIVIL_UNION,
    "O": MaritalStatus.OTHER,
}

# Person/veteran and Person/handicapped: 'Y', 'N', 'D' (declined to answer) or blank (not specified)
YES_NO_DECLINED = {
    "Y": YesNoDeclined.YES,
    "N": YesNoDeclined.NO,
    "D": YesNoDeclined.DECLINED,
    "": YesNoDeclined.NOT_SPECIFIED,
}

# Compensation/citizenshipStatus documents Z01 (a citizen of the United States), Z02 (a noncitizen national
# of the United States), Z03 (a lawful permanent resident), Z04 (an alien authorized to work). Live data
# sends the documented description instead of the code ("A citizen of the United States"), so both map (A-45).
_CITIZENSHIP_MEANINGS = {
    "Z01": ("a citizen of the United States", Citizenship.US_CITIZEN),
    "Z02": ("a noncitizen national of the United States", Citizenship.US_NONCITIZEN_NATIONAL),
    "Z03": ("a lawful permanent resident", Citizenship.LAWFUL_PERMANENT_RESIDENT),
    "Z04": ("an alien authorized to work", Citizenship.AUTHORIZED_ALIEN),
}
CITIZENSHIP = {code: value for code, (_, value) in _CITIZENSHIP_MEANINGS.items()}
CITIZENSHIP.update({text: value for _, (text, value) in _CITIZENSHIP_MEANINGS.items()})
CITIZENSHIP.update({text[0].upper() + text[1:]: value for _, (text, value) in _CITIZENSHIP_MEANINGS.items()})

# AchVoucher/accountType: C is "checking account or pay card", so it is never plain CHECKING (A-37 context)
DD_ACCOUNT_TYPE = {"C": AccountType.CHECKING_OR_PAY_CARD, "S": AccountType.SAVINGS, "IP": AccountType.INSTANT_PAY}

# AchVoucher/method
DD_METHOD = {
    "F": DepositMethod.FIXED_AMOUNT,
    "P": DepositMethod.PERCENT_BASE_UNSPECIFIED,
    "FS": DepositMethod.FIXED_AMOUNT_SKIP_IF_INSUFFICIENT,
    "PN": DepositMethod.PERCENT_OF_NET_AFTER_FIXED,
    "B": DepositMethod.REMAINDER,
}

# EmployeeDirectDeposit-HsaDepositSettings/method: here PN is "Percent of Net after Taxes" (A-37)
HSA_METHOD = {
    "F": DepositMethod.FIXED_AMOUNT,
    "P": DepositMethod.PERCENT_BASE_UNSPECIFIED,
    "B": DepositMethod.REMAINDER,
    "FS": DepositMethod.FIXED_AMOUNT_SKIP_IF_INSUFFICIENT,
    "PN": DepositMethod.PERCENT_OF_NET_AFTER_TAXES,
}

# AchVoucher/status and HsaDepositSettings/status
DD_STATUS = {"P": DepositStatus.PRENOTE, "D": DepositStatus.ACTIVE, "I": DepositStatus.INACTIVE}

# HsaDepositSettings/accountType: "EE/Co HSA to Checking/Savings"
HSA_ACCOUNT = {
    "HE": (AccountType.CHECKING, FundingParty.EMPLOYEE),
    "HES": (AccountType.SAVINGS, FundingParty.EMPLOYEE),
    "HC": (AccountType.CHECKING, FundingParty.EMPLOYER),
    "HCS": (AccountType.SAVINGS, FundingParty.EMPLOYER),
}

# EmployeeDirectDeposit/voucherType letters: 'R' (Regular), 'S' (Supplemental), 'V' (Vacation)
VOUCHER_SCOPE = {"R": PayKindScope.REGULAR, "S": PayKindScope.SUPPLEMENTAL, "V": PayKindScope.VACATION}

# DeductionCodeDetail/deductionType -> (category, tax treatment, catch-up)
DEDUCTION_TYPE = {
    "V": (Cat.VOLUNTARY, T.UNSPECIFIED, None),
    "C": (Cat.SECTION_125, T.PRE_TAX, None),
    "P": (Cat.POST_TAX_BENEFIT, T.POST_TAX, None),
    "F": (Cat.FSA, T.UNSPECIFIED, None),
    "G": (Cat.GARNISHMENT, T.UNSPECIFIED, None),
    "L": (Cat.LOAN, T.UNSPECIFIED, None),
    "K": (Cat.RETIREMENT, T.PRE_TAX, False),
    "KC": (Cat.RETIREMENT, T.PRE_TAX, True),
    "KE": (Cat.RETIREMENT, T.POST_TAX, False),
    "KL": (Cat.RETIREMENT_LOAN, T.UNSPECIFIED, None),
    "KR": (Cat.RETIREMENT, T.ROTH, False),
    "KCR": (Cat.RETIREMENT, T.ROTH, True),
}

# DeductionCodeDetail/calculationMethod (29 documented methods) -> (method, basis, rounding) (A-41)
CALCULATION_METHOD = {
    "F": (M.FIXED_AMOUNT, B.UNSPECIFIED, None),
    "PG": (M.PERCENT, B.GROSS_PAY, None),
    "PE": (M.PERCENT, B.GROSS_EARNINGS, None),
    "PS": (M.PERCENT, B.STRAIGHT_PAY, None),
    "PPR": (M.PERCENT, B.PAY_RATE, None),
    "PPRD": (M.PERCENT, B.PAY_RATE, Rounding.NEAREST_DOLLAR),
    "PPRM": (M.PERCENT, B.PRIOR_MONTH_PAY_RATE, Rounding.NEAREST_DOLLAR),
    "PR": (M.PERCENT, B.RETIREMENT_EARNINGS, None),
    "PGD": (M.PERCENT, B.GROSS_EARNINGS_LESS_DEDUCTIONS, None),
    "PET": (M.PERCENT, B.EARNINGS, None),
    "PCE": (M.PERCENT, B.CERTIFIED_JOB_EARNINGS, None),
    "PXG": (M.PER_TEN_THOUSAND, B.GROSS_PAY, None),
    "PXE": (M.PER_TEN_THOUSAND, B.GROSS_EARNINGS, None),
    "PXS": (M.PER_TEN_THOUSAND, B.STRAIGHT_PAY, None),
    "PXR": (M.PER_TEN_THOUSAND, B.RETIREMENT_EARNINGS, None),
    "R": (M.RATE_PER_HOUR, B.HOURS_WORKED, None),
    "RP": (M.RATE_PER_HOUR, B.HOURS_PAID, None),
    "RPS": (M.RATE_PER_HOUR, B.HOURS_PAID_SELECTED_CODES, None),
    "RC": (M.RATE_PER_HOUR, B.CERTIFIED_JOB_HOURS, None),
    "RUJ": (M.RATE_PER_HOUR, B.UNION_JOB_HOURS, None),
    "RUP": (M.RATE_PER_HOUR, B.UNION_PROJECT_HOURS, None),
    "RT": (M.RATE_TABLE, B.UNSPECIFIED, None),
    "G": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "K": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "U": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "UF": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "OH": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "OHSERS": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
    "IO": (M.PROVIDER_RULE, B.UNSPECIFIED, None),
}

# EmployeeDeductions-Deduction/basis
LIMIT_BASIS = {"M": LimitBasis.MONTH, "Q": LimitBasis.QUARTER, "A": LimitBasis.YEAR, "L": LimitBasis.LIFETIME}

# EmployeeDeductions-Deduction/matchMethod: 'F' (flat) or 'P' (percent)
MATCH_METHOD = {"F": M.FIXED_AMOUNT, "P": M.PERCENT}

# ScheduledDeduction/status: 'A' (active), 'I' (inactive), 'O' (one time)
SCHEDULED_STATUS = {"A": ElectionStatus.ACTIVE, "I": ElectionStatus.INACTIVE, "O": ElectionStatus.ONE_TIME}

# EmployeeLoanDetails/paymentFreq
LOAN_FREQUENCY = {"M": "MONTHLY", "P": "EVERY_PAY_PERIOD", "A": "ALL_PAY_TYPES"}

# BatchList/batchType: (R)egular, (M)anual, (S)pecial, (V)oid. The empty string seen live is undocumented.
BATCH_TYPE = {
    "R": PayrollRunType.REGULAR,
    "M": PayrollRunType.MANUAL,
    "S": PayrollRunType.SPECIAL,
    "V": PayrollRunType.VOID,
}

# BatchList/batchStatus codes are undocumented; COMP is evidenced by printed vouchers (A-21).
BATCH_STATUS = {"COMP": PayrollRunStatus.COMPLETED}

# PayrollVoucher/type. V here is Vacation, unlike BatchList/batchType where V is Void.
VOUCHER_TYPE = {
    "R": PayStatementType.REGULAR,
    "V": PayStatementType.VACATION,
    "S": PayStatementType.SUPPLEMENTAL,
    "A": PayStatementType.ARREARS,
    "J": PayStatementType.ADJUSTMENT,
}

# ClientCodes-PayCode/payClass (also carried on voucher earning lines)
PAY_CLASS = {
    "E": EarningKind.EARNINGS,
    "R": EarningKind.REIMBURSEMENT,
    "F": EarningKind.NON_CASH_FRINGE,
    "RT": EarningKind.REPORTED_TIPS,
    "M": EarningKind.MEMO,
}

# ClientCodes-PayCode/payReason: hours (H) or units (U) (A-38)
PAY_REASON = {"H": QuantityUnit.HOURS, "U": QuantityUnit.UNITS}
