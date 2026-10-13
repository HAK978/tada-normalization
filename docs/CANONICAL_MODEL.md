# Canonical model (draft for review)

Status: **draft, 2026-10-12**. It is built from the provider specs in `contracts/` and a read-only
sample of the live demo tenants (see [ASSUMPTIONS.md](../ASSUMPTIONS.md) for every piece of
evidence). Nothing below is implemented yet.

## 1. Principles

1. **A company is the business the employees work for.** Employer and tax identity are separate
   fields, recorded in each provider's own terms. Under PrismHR PEO and ASO arrangements, "company
   = legal employer" would be wrong (A-30).
2. **Never lose the original.** Every coded value keeps the provider's raw value, its source field
   and the provider's own label. Any source field not mapped to a canonical field is kept verbatim in
   `provider_extensions`, except for a short drop list where each entry has a stated reason (§6).
3. **Map meaning only with evidence.** A code is translated only when one of these supports it:
   - the provider documents it;
   - the provider supplies its own label or classification for it;
   - arithmetic on live data proves it.

   Otherwise it becomes `UNMAPPED` with a diagnostic. Customer-configured codes (Prism status codes,
   UKG employee types) are mapped through the provider's own classification field when one exists,
   and are never mapped from their names.
4. **Units are explicit.** Money carries a currency. Every rate says what period it covers. Hours
   are hours. Percentages are percentage points (`"3"` means 3%).
5. **Derived values say so.** Anything we calculate carries `derived: true` and its formula.
6. **Sensitive identifiers are reduced.** SSNs and bank account numbers keep only their last 4
   digits in our output, whatever the provider sent.
7. **Output is deterministic.** Anything time-dependent, such as "is this deposit active?", is
   evaluated against an explicit `as_of` date, never the clock.

## 2. Building blocks

**Coded value.** Every enum-like field uses this shape:

```json
{"value": "ON_LEAVE", "raw": "L", "label": "Leave of Absence", "source_field": "client.employeeStatus"}
```

- `value`: a canonical code, or `UNMAPPED`.
- `raw`: exactly what the provider sent.
- `label`: the provider's own description, when one exists. Sources include the Prism client code
  tables, UKG `display_name` and isolved descriptions.

**Money, rate, hours and percent:**

```json
{"amount": "2375.00", "currency": "USD"}
{"amount": "59.375", "currency": "USD", "per": "HOUR"}
{"hours": "8", "per": "DAY"}
{"percent": "3"}
```

- Decimals are serialized as strings, so float rounding never changes a value.
- The currency is taken from the provider when it states one (UKG). Otherwise it is USD (A-31).

**A derived value:**

```json
{"amount": "1880.00", "currency": "USD", "derived": true, "formula": "sum(earnings[].amount)"}
```

**Fields on every record:**

```json
"id": "prismhr:970592:employee:102:E1001",
"source": {"provider": "prismhr", "tenant_id": "970592",
           "endpoints": ["employee/v1/getEmployee"], "ids": {"clientId": "102", "employeeId": "E1001"}},
"provider_extensions": {"person.vehicleDetails": []},
"diagnostics": [{"code": "UNMAPPED_CODE", "severity": "warning",
                 "field": "compensation.hourlyPayPeriod", "raw": "Q", "message": "..."}]
```

IDs have the form `{provider}:{tenant}:{entity}:{source ids}`. They are stable across runs, so
records can be linked and diffed.

## 3. Entities

```
Company ──< Employee ──< DirectDeposit
   │            ├─────< DeductionElection
   │            └─────< PayStatement >── PayrollRun
   └──────────────────────────────────────────┘
```

### 3.1 Company

| Field | Meaning | PrismHR | isolved | UKG Ready |
|---|---|---|---|---|
| `name`, `legal_name` | Trading and legal names | `clientName`, `legalName` | `dbaName`, `legalName` | none; no company endpoint (A-15) |
| `parent` | Grouping above the company | none | the isolved client (id, name) | none |
| `status` | `ACTIVE` `PENDING` `INACTIVE` `TERMINATING` `TERMINATED` | `statusClass` A/P/I/C/T (documented) | `status` text | none |
| `own_tax_id` | The company's own FEIN as returned (last 4 if visible) | `federalIdNumber`, fully masked live | `federalEIN` | none |
| `service_arrangement` | `PEO` `ASO` `PAYROLL_ONLY` `ASO_ALT_BILLING` `CORPORATE_PAYROLL` `HR_ONLY` | `serviceType` (documented) | none | none |
| `employers[]` | Employers or EINs the employees are assigned to, in provider terms | `employerId` + `altEmployer[]`; names and EINs not retrievable (403, A-09) | the legal company itself | `lookup/eins` |
| `pay_groups[]` | id, name, frequency | `getClientCodes` PGroups + `getPayrollSchedule` | legal company `payGroups` | not fetched |
| `address`, `phone`, `email` | Main contact details | client master | `legalAddress` | none |

### 3.2 Employee

| Group | Fields |
|---|---|
| Identity | `identifiers[]` of {type, value}: `PROVIDER_ID`, `EMPLOYEE_NUMBER`, `EXTERNAL_ID`, `CLOCK_NUMBER`. Also `national_id`: {type, last4, masked_at_source}. |
| Name | `first`, `middle`, `last`, `preferred`, `prefix`, `suffix` |
| Personal | `birth_date`, `gender`, `marital_status` and `ethnicity` (all coded, label kept), plus veteran and disability flags |
| Contact | `addresses[]` (HOME, MAILING, ...), `phones[]` (HOME, MOBILE, WORK, ...), `emails[]` (PERSONAL, WORK) |
| Employment | `status` (`ACTIVE` `ON_LEAVE` `TERMINATED`) with its date, `employment_type` (`FULL_TIME` `PART_TIME`), hire / rehire / start / seniority / termination dates, `termination_reason`, `flsa_exempt` |
| Job | `title`, `job_code`, `department`, `division`, `location`, `manager`, `supervisor`, `union` |
| Compensation | `pay_type` (`SALARY` `HOURLY` `COMMISSION` `DRIVER` `CONTRACTOR_1099`), `pay_frequency` with `periods_per_year`, `rates[]` (every rate the provider gives, each with its own `per`), `annual_pay` (as provided, or derived and flagged), `standard_hours`, `effective_date`, `history[]` |
| Tax setup | Federal and state withholding settings: mapped if time allows, otherwise kept in `provider_extensions` |

| | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| IDs | `employeeId`; `client.clientEmployeeId`; `client.clockNum` | `id`; `employeeNumber` | `id` (account), `employee_id`, `external_id` |
| SSN | `compensation.ssn`, fully masked live (no last 4) | not returned by this endpoint | returned in full live; reduced to last 4 |
| Status | `client.statusClass` A/L/T (documented); the client status code and its label from `getClientCodes` | `employmentStatus` text, mapped via the client's status table | `status` "Active"/"Terminated": undocumented, but matches `dates.terminated` on 15/15 live |
| Type | `client.typeClass` F/P (documented as the `getEmployeeList` filter), plus the client type code and label | `employmentCategoryCode` (client-configured): `UNMAPPED` + label | pay-info `employee_type`, a tenant lookup name: `UNMAPPED` + label |
| Pay | `payMethod` S/H/C/D. `salary` is per pay period (proven, A-20). `hourlyPay` is per hour. `hourlyPayRate` is per `hourlyPayPeriod`, where live `A` = annual (proven, A-19). | `payType`; `hourlyRate` per hour; `perPaySalary` per pay period; `annualSalary`; `payFrequency` via Frequencies (A-27) | compensation history: `amount` per `amount_period`, `hourly_pay` per hour, `time` in ms per `time_period`, `num_pp_in_year`; pay-info `standard_work_day` in ms |

### 3.3 DirectDeposit

**Fields:**
- `account`: `type`, `routing_number`, `account_last4` and `bank_name`.
- Allocation: `method`, `amount`, `percent` and `limit`.
- `sequence` and `is_remainder`.
- `status` and `prenote_status`.
- `effective_from` and `effective_to`.
- `applies_to`: the pay types the deposit applies to (Prism only).

| Canonical method | PrismHR `method` (documented) | isolved | UKG `calc_method.type` |
|---|---|---|---|
| `FIXED_AMOUNT` | F | `amount` set | FLAT_AMOUNT |
| `FIXED_AMOUNT_SKIP_IF_INSUFFICIENT` | FS | none | none |
| `PERCENT_BASE_UNSPECIFIED` | P (no base stated) | `percent` set (no base stated) | none |
| `PERCENT_OF_GROSS` | none | none | GROSS_EARNING |
| `PERCENT_OF_NET` | none | none | NET_PAY |
| `PERCENT_OF_NET_AFTER_FIXED` | PN | none | none |
| `PERCENT_OF_REMAINDER` | none | none | DIRECT_DEPOSIT_PER_OF_REMAINDER |
| `REMAINDER` | B | `sequenceNumber` 0 ("0 = Net Pay") | FULL ("Entire/Remainder" live) |

Prism `PN` and UKG's percent-of-remainder look alike but are kept apart: neither provider documents
that they are the same. For UKG percent methods the meaning comes from the enum name alone, since live
data only showed `FULL`, so the converter checks `display_name` whenever it is present (A-26).

| Canonical account type | Source |
|---|---|
| `CHECKING`, `SAVINGS` | Prism C/S; isolved "Checking"/"Savings"; UKG CHECKING/SAVINGS |
| `CHECKING_OR_PAY_CARD` | Prism C: documented as "checking account or pay card", so it can't be called plain checking |
| `INSTANT_PAY` | Prism IP |
| `PAPER_CHECK` | UKG RESERVE_LIVE_CHECK, which reserves a paper check rather than naming an account |

`status` is `ACTIVE`, `INACTIVE` or `PRENOTE`. It comes from Prism D/I/P or isolved "Active"/"Inactive".
For UKG it is derived from the `active` flag together with `active_from`/`active_to` at `as_of`.

### 3.4 DeductionElection (setup)

**Fields:**
- `code`, `label`, `category`, `tax_treatment` and `catch_up`.
- `calculation`: method, amount, percent and rate.
- `limits`: per-period limit, maximum, and the maximum's basis.
- `frequency`, `effective_from` and `effective_to`.
- `employer_match`.
- Garnishment details: case number, type and payee.
- Loan details: principal, payback amount and amount paid.

| Category / tax treatment | PrismHR `deductionType` (documented) | isolved `systemBenefitType` (provider classification) |
|---|---|---|
| `RETIREMENT` / `PRE_TAX` | K; KC with `catch_up` | 401(k), tax treatment `UNSPECIFIED` |
| `RETIREMENT` / `POST_TAX` | KE | none |
| `RETIREMENT` / `ROTH` | KR; KCR with `catch_up` | none |
| `RETIREMENT_LOAN` | KL | none |
| `SECTION_125` / `PRE_TAX` | C | Medical, Dental and Vision "Pre-Tax 125" |
| `FSA` | F | FSA Medical; FSA Dependent Care |
| `HSA` | none | Health Savings Account |
| `POST_TAX_BENEFIT` / `POST_TAX` | P | none |
| `VOLUNTARY` | V | system pay item "Voluntary Deduction" |
| `GARNISHMENT` | G (details: 403, A-08) | `/garnishments` |
| `LOAN` | L (`getEmployeeLoans`) | none |

UKG exposes no deduction setup on this tenant (A-12). UKG deductions appear only as pay-statement
lines, which carry names only, so their category stays `UNMAPPED` with the label kept.

### 3.5 PayrollRun

**Fields:** `pay_date`, `period_start`, `period_end`, run and processed dates, `type`, `status`, the
pay groups, and the employer or EIN.

- **Types:** `REGULAR` `SPECIAL` `MANUAL` `VOID` `ADJUSTMENT` `CORRECTION` `HISTORICAL_IMPORT`.
  - Prism `batchType` R/M/S/V is documented. The empty string seen live is `UNMAPPED`.
  - isolved run types are text ("Regular Payroll", "Data Conversion").
  - UKG types come from the `payroll-types` lookup.
- **Status:** `OPEN` `CLOSED` `SUBMITTED` `COMPLETED` `NOT_PROCESSED` `FAILED`, always with the raw value.
  - Prism status codes are undocumented. `COMP` maps to `COMPLETED` on evidence; the rest stay
    `UNMAPPED` (A-21).

### 3.6 PayStatement (paycheck)

**Header:** pay date, period, check number, `type`, status, void details, run, employee.

**Totals:** `gross_pay`, `gross_wages` (isolved only), `net_pay`, employee taxes, employer taxes,
deductions and employer contributions. Each total is either provided by the source or derived and
flagged.

**Lines:**
- `earnings[]`: code, label, `kind`, hours, units, rate, amount, plus department, job and location.
  `kind` is one of `EARNINGS` `REIMBURSEMENT` `NON_CASH_FRINGE` `REPORTED_TIPS` `MEMO`.
- `taxes[]`: code, label, `paid_by` (`EMPLOYEE`/`EMPLOYER`), amount, taxable wages.
- `deductions[]`: code, label, category, employee amount, employer amount.
- `employer_contributions[]`: code, label, amount.
- `payments[]`: `DIRECT_DEPOSIT` or `CHECK`, amount, account last 4.

| | PrismHR voucher | isolved check | UKG pay statement |
|---|---|---|---|
| Gross | `totalEarnings` | `grossPay` (reconciles to net), plus `grossWages` = sum of non-memo earnings (A-28) | **derived**: the API has no total |
| Net | `netPay` | `netPay` | **derived** from payments: the API has no total |
| Hours | `hoursUnits` | `checkHours` | `hours` is in **milliseconds**, divided by 3,600,000 (proven, A-24) |
| Line amount | `payAmount` = hours × `unitRate` (proven; the doc says "per hour", A-18) | `checkDollars` (equals `currentDollars` live) | `ee_amount` |
| Earning kind | `payClass` E/R/F/RT/M (documented) | `isMemoEarning` | none: `UNMAPPED` |
| Taxes | `employeeTax[]` (employee), `companyTax[]` (employer) | `taxes[]` with `isEmployeeTax` | `taxes[]` with `ee_amount` and `er_amount` |
| Deductions | `deduction[]` (documented `deductType`), `otherDeduction[]` | `deductions[]`, `garnishments[]` | `deductions[]` (`ee_amount`) |
| Employer contributions | `employerContributions[]` | `benefits[].checkEmployerContribution` | `deductions[].er_amount` |
| Payments | `checkAmt` + `directDeposit[]` | `checkAmount` + `directDeposits[]` | `payments[]` |

**Built-in checks, which are reported and never "fixed":**
- gross − employee taxes − deductions = net;
- payments = net;
- provided total = sum of its lines.

## 4. What is deliberately not requested or not mapped

- **Prism `Health` option:** never requested, because it is medical data.
- **isolved profile pictures, document contents and I-9 documents:** never requested (images and
  identity documents).
- **Year-to-date and other accumulator buckets, workers' comp and GL distributions:** kept in
  `provider_extensions`, not mapped.
- **Provider checksums (update tokens):** kept in `provider_extensions`. The dry-run write path may use them.

## 5. Open questions for review

1. **Tax withholding setup:** map it into canonical fields, or keep it in `provider_extensions` for v1?
2. **Customer-configured labels** such as UKG "FT Exempt": keep them `UNMAPPED` with the label (strict),
   or add an optional per-tenant mapping file later?
3. **Output:** JSON per entity first, with SQLite as a stretch goal. Is that OK?
