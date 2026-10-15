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
    ContactRole,
    DeductionCategory as Cat,
    DepositMethod,
    DepositStatus,
    EarningCategory,
    EarningKind,
    ElectionStatus,
    EmploymentChangeKind,
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
    TaxType,
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

# Person/gender lists "M, F, X or D" without meanings; NewHireEmployee/gender, the same employee field when it
# is set, defines them: "'M' (male), 'F' (female), 'X' (non-binary), 'D' (declined) or 'U' (unknown)" (A-44).
# U isn't in Person's list, and the canonical enum has no "unknown" (that is a missing value), so it stays UNMAPPED.
GENDER = {"M": Gender.MALE, "F": Gender.FEMALE, "X": Gender.NON_BINARY, "D": Gender.DECLINED}

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

# HistoryRecord holds one change, named by the object it carries: StatusChange ("employee status, such as
# active"), Leave ("leave of absence") or Termination (A-76)
HISTORY_EVENT = {
    "statusChange": EmploymentChangeKind.STATUS,
    "leave": EmploymentChangeKind.LEAVE,
    "termination": EmploymentChangeKind.TERMINATION,
}

# Dependents/relationType: "'D' (Dependent) or 'B' (Beneficiary only)" (A-77)
DEPENDENT_RELATION_TYPE = {"D": (ContactRole.DEPENDENT,), "B": (ContactRole.BENEFICIARY,)}
# Dependents/beneficiaryType: "'P' (Primary) or 'C' (Contingent)"; either way the person is a beneficiary
BENEFICIARY_TYPES = frozenset({"P", "C"})
# Dependents/status: "'A' (Active), 'I' (Inactive), or 'P' (Pending)"; pending is neither, so it stays raw
DEPENDENT_STATUS = {"A": True, "I": False}

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

# ClientCodes-PayCode/talxPayType, "download code used for employment verification" (documented on
# GetPaycodeDetailsResponse.PayCode; getClientCodes sends the same field): PrismHR's own category of a
# pay code (A-67). Wages and Miscellaneous are known but not specific, so they are OTHER.
TALX_PAY_TYPE = {
    "R": EarningCategory.REGULAR,
    "V": EarningCategory.VACATION,
    "S": EarningCategory.SICK,
    "B": EarningCategory.BONUS,
    "E": EarningCategory.SEVERANCE,
    "H": EarningCategory.HOLIDAY,
    "P": EarningCategory.PENSION,
    "W": EarningCategory.OTHER,
    "O": EarningCategory.OVERTIME,
    "C": EarningCategory.COMMISSION,
    "T": EarningCategory.TIPS,
    "M": EarningCategory.OTHER,
    "K": EarningCategory.WORKERS_COMPENSATION,
}
# ClientCodes-PayCode/rateClass: 'D' (Doubletime). The other rate classes don't say what the pay is
# for ('P' Premium is used live by both "Overtime" and "Half Time"), so they set no category (A-67).
RATE_CLASS_DOUBLETIME = "D"

# Voucher employeeTax[].empTaxDeductCode / companyTax[].comTaxDeductCode, documented only as "tax
# deduction code". The meaning comes from PrismHR's own description of each code
# (empTaxDeductCodeDesc / comTaxDeductCodeDesc), identical for all 25 live clients, and the amounts
# agree with the statutory rates (A-68). Federal codes, exactly:
FEDERAL_TAX = {
    "00-10": TaxType.FEDERAL_INCOME,  # "Federal Income Tax"
    "00-11": TaxType.MEDICARE,  # "Medicare - Employee": 1.45% of taxable on 2,254 of 2,273 lines
    "00-12": TaxType.SOCIAL_SECURITY,  # "Soc Security - Employee": 6.2% on 2,263 of 2,273
    "00-15": TaxType.MEDICARE,  # "Medicare - Employer": comTaxRate 0.0145
    "00-16": TaxType.SOCIAL_SECURITY,  # "Soc Security - Employer": comTaxRate 0.062
    "00-17": TaxType.FEDERAL_UNEMPLOYMENT,  # "Fed Unemployment": comTaxRate 0.006
}
# State codes are "<2-digit state>-<2-digit tax>". A tax number is listed only where it means the
# same thing in every state it was seen in live; the rest (26, 27, 28, 41, 42, ...) mix different
# taxes or have no description, so they stay UNMAPPED.
STATE_TAX = {
    "20": TaxType.STATE_INCOME,  # "<ST> Income Tax": 35 of 35 states
    "21": TaxType.STATE_DISABILITY,  # "CA/NJ/NY Disability", "PR DISABILITY INSURANCE": 4 of 4
    "22": TaxType.STATE_UNEMPLOYMENT,  # "PA SUI EMPLOYEE TAX", "NJ UI/WF", "ALASKA SUTA EE": 3 of 3
    "24": TaxType.STATE_UNEMPLOYMENT,  # "<ST> Unemployment" (NJ "SUTA/WF/HC"): 40 of 40
    "25": TaxType.STATE_DISABILITY,  # "HAWAII SDI TAX", "NJ ER SDI", "PR DISABILTY INSURANCE": 3 of 3
    "40": TaxType.STATE_PAID_LEAVE,  # "<state> Paid Family Medical Leave": 5 of 5
}
# Local codes are "<5- or 9-digit locality>-<2-digit tax>". CIWT is the city income withholding tax.
LOCAL_TAX = {
    "31": TaxType.LOCAL_INCOME,  # "<city>, <ST> CIWT": 22 of 22 localities
    "39": TaxType.LOCAL_INCOME,  # "Philadelphia, Philadelphia, PA Resident CIWT"
}

# Failures whose message says there is nothing to return (A-70). The spec documents 400 and 404 only
# generically, but live, getBatchListByDate answers an empty date range with 404 "No batches could be
# found for the date range specified (...)" (67 requests) and a client without payroll with 400 "No
# batches exist for client ..." (156 requests). Every other failure leaves its data unknown.
EMPTY_MESSAGES = {
    "payroll/v1/getBatchListByDate": ("No batches could be found", "No batches exist"),
    # HTTP 404 "Scheduled payment for employee '<id>' in client '<id>' does not exist." (live, A-70)
    "payroll/v1/getScheduledPayments": ("Scheduled payment for employee",),
}
