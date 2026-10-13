"""isolved code tables. isolved sends descriptions rather than codes; each table maps the exact
description text of a provider-level lookup or documented field (cited per table).

Spec: contracts/isolved/openapi/isolved-v6.swagger.json (the primary snapshot only).
"""

from normalization.canonical.codes import (
    AccountType,
    Citizenship,
    DeductionCategory as Cat,
    DepositStatus,
    EmploymentStatus,
    Gender,
    MaritalStatus,
    PayFrequency,
    PayrollRunStatus,
    PayrollRunType,
    PayStatementType,
    PayType,
    TaxTreatment as T,
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
