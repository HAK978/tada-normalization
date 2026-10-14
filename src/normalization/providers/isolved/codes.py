"""isolved code tables. isolved sends descriptions rather than codes; each table maps the exact
description text of a provider-level lookup or documented field (cited per table).

Spec: contracts/isolved/openapi/isolved-v6.swagger.json (the primary snapshot only).
"""

from normalization.canonical.codes import (
    AccountType,
    Citizenship,
    DeductionCategory as Cat,
    DepositStatus,
    EarningCategory,
    EarningKind,
    EmploymentStatus,
    Gender,
    MaritalStatus,
    PayFrequency,
    PayrollRunStatus,
    PayrollRunType,
    PayStatementType,
    PayType,
    TaxTreatment as T,
    TaxType,
)

# /api/lookup/genders: F Female, M Male, X Non-binary, N Chose not to answer (live lookup)
GENDER = {
    "Female": Gender.FEMALE,
    "Male": Gender.MALE,
    "Non-binary": Gender.NON_BINARY,
    "Chose not to answer": Gender.DECLINED,
}

# /api/lookup/maritalStatuses (live lookup)
MARITAL = {
    "Single": MaritalStatus.SINGLE,
    "Married": MaritalStatus.MARRIED,
    "Divorced": MaritalStatus.DIVORCED,
    "Widowed": MaritalStatus.WIDOWED,
    "Civil Union": MaritalStatus.CIVIL_UNION,
    "Separated": MaritalStatus.SEPARATED,
    "Legally Separated": MaritalStatus.LEGALLY_SEPARATED,
    "Registered Domestic Partner": MaritalStatus.DOMESTIC_PARTNER,
    "Chose not to answer": MaritalStatus.DECLINED,
}

# /api/lookup/citizenships. "National of the United States" is left out on purpose: it does not
# say whether it means a citizen or a noncitizen national. "Unknown" stays UNMAPPED.
CITIZENSHIP = {
    "Citizen of the United States": Citizenship.US_CITIZEN,
    "Alien Authorized to Work": Citizenship.AUTHORIZED_ALIEN,
    "Lawful Permanent Resident": Citizenship.LAWFUL_PERMANENT_RESIDENT,
}

# /api/system/payTypes descriptions (live lookup). Draw and Bonus are not a pay basis; 1099 is a
# worker classification, not a pay type (A-39).
PAY_TYPE = {
    "Hourly": PayType.HOURLY,
    "Auto Hourly": PayType.HOURLY,
    "Salary": PayType.SALARY,
    "Salary (Variable Hours)": PayType.SALARY,
    "Salary (Variable Entered Hours)": PayType.SALARY,
    "Salary Non-Exempt": PayType.SALARY,
    "Commission": PayType.COMMISSION,
}
CONTRACTOR_PAY_TYPE = "1099"

# Employment status descriptions that appear as implied system statuses (statusId -1,
# isImpliedStatus true) in /statuses history (A-48). Customer-defined statuses stay UNMAPPED.
IMPLIED_STATUS = {"Active": EmploymentStatus.ACTIVE, "Terminated": EmploymentStatus.TERMINATED}

# /api/lookup/Frequencies descriptions -> (frequency, periods per year). Matched by description,
# never by ID; "N Pay Periods Per Year" is parsed (A-27).
FREQUENCY = {
    "Weekly": (PayFrequency.WEEKLY, 52),
    "Bi-Weekly": (PayFrequency.BIWEEKLY, 26),
    "Semi-Monthly": (PayFrequency.SEMIMONTHLY, 24),
    "Monthly": (PayFrequency.MONTHLY, 12),
    "Quarterly": (PayFrequency.QUARTERLY, 4),
    "Semi-Annual": (PayFrequency.SEMIANNUALLY, 2),
    "Annually": (PayFrequency.ANNUALLY, 1),
}

# EmployeeDirectDepositModel/accountType ("Bank Acount Type Description"), live values
DD_ACCOUNT_TYPE = {"Checking": AccountType.CHECKING, "Savings": AccountType.SAVINGS}

# EmployeeDirectDepositModel/status ("Direct Deposit Status Description"), live values
DD_STATUS = {"Active": DepositStatus.ACTIVE, "Inactive": DepositStatus.INACTIVE}

# ClientPayItemModel/systemBenefitType + systemPayItemType: provider-level classification of a
# pay item (A-49). Keyed by (benefit type, pay item type); None matches any pay item type.
DEDUCTION_CLASS = {
    ("401(k)", "401K Loan"): (Cat.RETIREMENT_LOAN, T.UNSPECIFIED),
    ("401(k)", "401(k) Roth"): (Cat.RETIREMENT, T.ROTH),
    ("401(k)", None): (Cat.RETIREMENT, T.UNSPECIFIED),
    ("Medical Pre-Tax 125", None): (Cat.SECTION_125, T.PRE_TAX),
    ("Dental Pre-Tax 125", None): (Cat.SECTION_125, T.PRE_TAX),
    ("Vision Pre-Tax 125", None): (Cat.SECTION_125, T.PRE_TAX),
    ("FSA Medical", None): (Cat.FSA, T.UNSPECIFIED),
    ("FSA Dependent Care", None): (Cat.FSA, T.UNSPECIFIED),
    ("Health Savings Account", "HSA Pre-tax"): (Cat.HSA, T.PRE_TAX),
    ("Health Savings Account", "HSA After-tax"): (Cat.HSA, T.POST_TAX),
    ("Health Savings Account", None): (Cat.HSA, T.UNSPECIFIED),
    (None, "Voluntary Deduction"): (Cat.VOLUNTARY, T.UNSPECIFIED),
}
# A system pay item type that says "post-tax" overrides an unspecified treatment (e.g. "FSA Medical post-tax").
POST_TAX_MARKERS = ("post-tax", "after-tax")

# Earning kind of a non-memo check line, from its client pay item's system classification (A-53).
# Evidence per entry: the /api/system/earnings description of that system earning, quoted in A-53,
# or live arithmetic (grossWages - grossPay = the Group Term Life lines on 15 of 15 checks).
EARNING_BENEFIT_CLASS = {"Group Term Life": EarningKind.NON_CASH_FRINGE}
EARNING_CLASS = {
    "Regular": EarningKind.EARNINGS,
    "Overtime - Blended Rate": EarningKind.EARNINGS,
    "Overtime @ Flat 1.5": EarningKind.EARNINGS,
    "Vacation": EarningKind.EARNINGS,
    "Sick": EarningKind.EARNINGS,
    "Holiday": EarningKind.EARNINGS,
    "Bonus": EarningKind.EARNINGS,
    "Commission": EarningKind.EARNINGS,
    "Other Hrs or Dollars": EarningKind.EARNINGS,
    "ShiftDiff": EarningKind.EARNINGS,
    "Misc Non Taxable": EarningKind.REIMBURSEMENT,
}

# Category of an earnings line, from the system earning its client pay item is built on (A-67): each
# system earning's title and description in /api/system/earnings (quoted in A-53 and A-67).
EARNING_CATEGORY = {
    "Regular": EarningCategory.REGULAR,
    "Overtime @ Flat 1.5": EarningCategory.OVERTIME,  # "Overtime paid at 1.5 ee hourly rate."
    "Overtime - Blended Rate": EarningCategory.OVERTIME,  # "Blended rate used to pay OT hours"
    "Vacation": EarningCategory.VACATION,
    "Sick": EarningCategory.SICK,
    "Holiday": EarningCategory.HOLIDAY,
    "Bonus": EarningCategory.BONUS,
    "Commission": EarningCategory.COMMISSION,
    "ShiftDiff": EarningCategory.SHIFT_DIFFERENTIAL,  # "Shift Diff"
    "Other Hrs or Dollars": EarningCategory.OTHER,  # "Use for any earnings where entry of hr / dollars is needed."
    "1099M Earnings- Hrs or Dollars": EarningCategory.NON_EMPLOYEE_COMPENSATION,  # "1099M earnings ... Box 7"
    "1099M Non EE Comp": EarningCategory.NON_EMPLOYEE_COMPENSATION,  # "1099M non employee compensation (box 7)"
}
# A system benefit type that classifies a pay item whose system earning isn't listed above: live, the
# Vacation, Sick and Holiday items all sit under "Leave Accrual", which pays accrued leave.
EARNING_BENEFIT_CATEGORY = {"Leave Accrual": EarningCategory.PAID_TIME_OFF}

# CheckTaxAccumulationModel/itemDescription (A-68). itemCode is null live; the description is the
# system tax's ("taxDescription: Description of the system tax", LegalTaxModel). Federal taxes exactly;
# SOC SEC and MED withhold exactly 6.2% and 1.45% of taxable wages on all 40 live checks.
FEDERAL_TAX = {
    "FEDERAL WH": TaxType.FEDERAL_INCOME,
    "SOC SEC EE": TaxType.SOCIAL_SECURITY,
    "SOC SEC ER": TaxType.SOCIAL_SECURITY,
    "MED EE": TaxType.MEDICARE,
    "MED ER": TaxType.MEDICARE,
    "FUTA ER": TaxType.FEDERAL_UNEMPLOYMENT,
}
# State taxes are "<state> <tax>", the state as a USPS code or full name ("PA WH", "CALIFORNIA WH",
# "PENNSYLVANIA SUI ER"). Anything else, local taxes included, stays UNMAPPED.
STATE_TAX = {
    "WH": TaxType.STATE_INCOME,
    "SUI EE": TaxType.STATE_UNEMPLOYMENT,
    "SUI ER": TaxType.STATE_UNEMPLOYMENT,
    "SDI EE": TaxType.STATE_DISABILITY,
    "SDI ER": TaxType.STATE_DISABILITY,
}

# PayrollRunHistoryModel/payrollRunType and /status descriptions (live values)
RUN_TYPE = {"Regular Payroll": PayrollRunType.REGULAR, "Data Conversion": PayrollRunType.HISTORICAL_IMPORT}
RUN_STATUS = {
    "Completed Payroll Run": PayrollRunStatus.COMPLETED,
    "Payroll Not Processed": PayrollRunStatus.NOT_PROCESSED,
}

# CheckModel/checkTypeDescription (live value "Adjustment"); conversion runs mark the check as imported
CHECK_TYPE = {
    "Regular": PayStatementType.REGULAR,
    "Adjustment": PayStatementType.ADJUSTMENT,
    "Manual": PayStatementType.MANUAL,
}

# GET responses the spec documents as "nothing found" (A-70): a 404 from these lists is an empty
# result, not missing data. Quoted from each operation's 404 response description.
EMPTY_RESPONSES = {
    "api/clients/{client}/payItems": {404: "No pay items found."},
    "api/clients/{client}/legals/{legal}/checks": {404: "No checks found for check date or date range."},
    "api/clients/{client}/legals/{legal}/employees": {404: "No employees found"},
    "api/clients/{client}/legals/{legal}/employees/{id}/directdeposits": {404: "No employee direct deposits found."},
    "api/clients/{client}/legals/{legal}/employees/{id}/garnishments": {404: "No employee garnishments found."},
    "api/clients/{client}/legals/{legal}/employees/{id}/payItems": {404: "No employee pay items found"},
    "api/clients/{client}/legals/{legal}/employees/{id}/payRates": {404: "No employee alternate pay rates found."},
    "api/clients/{client}/legals/{legal}/employees/{id}/salaries": {404: "No employee salaries found."},
    "api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory": {404: "No payroll run history found."},
    "api/corestream/clients/{client}/legals/{legal}/employees/{id}/deductions": {404: "No employee deductions found."},
    "api/lookup/Frequencies": {404: "No frequency records found."},
    "api/system/earnings": {404: "No system earnings found."},
    "api/system/payTypes": {404: "No system pay types were found."},
}
