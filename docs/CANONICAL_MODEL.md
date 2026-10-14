# Canonical model

Status: **implemented, 2026-10-13.**
- v1 had review decisions (§10).
- An independent design audit raised 15 findings. All were verified against the specs and folded
  in here and in [ASSUMPTIONS.md](../ASSUMPTIONS.md).
- Building the three converters refined it further, each change recorded in ASSUMPTIONS.md (A-44
  onward).

Implemented: the model itself (`src/normalization/canonical/`) and the PrismHR, isolved and UKG Ready
converters. The model is exported as JSON Schema, one file per record type, under `schemas/`
(`python -m normalization schema`). Output is JSON per record type plus SQLite (A-36). What happens to
every source field is listed in [FIELD_COVERAGE.md](FIELD_COVERAGE.md) (A-62).

## 1. Principles

1. **A company is the business the employees work for.** Employer and tax identity are separate
   fields, recorded in each provider's own terms (A-30).
2. **Never lose the original.** Every coded value keeps the provider's raw value, its source field
   and the provider's own label. Source fields with no canonical home are kept in
   `provider_extensions`. Two exceptions apply: sensitive values are sanitized (principle 6), and a
   short drop list exists (§9). §9 also gives every relevant field an explicit disposition.
3. **Map meaning only with evidence.** Acceptable evidence:
   - the provider's documentation;
   - a provider-supplied label or classification (for example a UKG `display_name`, an isolved system
     benefit type, or a Prism code-table description);
   - arithmetic on live data.

   Enum *names* alone are not evidence. Customer-configured labels stay `UNMAPPED`.
4. **Units and bases are explicit.**
   - Money carries a currency, and every rate says what period it covers.
   - Quantities say whether they are hours or units.
   - Percentages say what they are a percentage *of*, and whether their scale is verified.
5. **Derived values say so.** Anything we calculate carries `derived: true` and its formula.
6. **Sensitive values are sanitized everywhere.** SSNs and bank account numbers keep at most their
   last 4 digits. This applies to canonical fields, `provider_extensions`, raw values and diagnostics
   alike. A value the provider already masked yields no last 4: we never invent digits.
7. **Output is deterministic and exact.**
   - Time-dependent values are evaluated at an explicit `as_of` date.
   - Numbers are parsed as decimals from the original JSON text, never through floats.

## 2. Building blocks

**Coded value:**

```json
{"value": "ON_LEAVE", "raw": "L", "label": "Leave of Absence", "source_field": "client.employeeStatus"}
```

`value` is a canonical code or `UNMAPPED`. The meaning of a raw code is always looked up by
**provider + full source field**, never by the code alone. Prism's `V` means Void in a batch type,
Vacation in a voucher type, and Reversal in payroll history.

**Money, rates and quantities:**

```json
{"amount": "2375.00", "currency": "USD"}
{"amount": "59.375", "currency": "USD", "per": "HOUR"}
{"value": "8", "unit": "HOURS"}
{"value": "12", "unit": "UNKNOWN", "raw": "12"}
```

- Decimals are strings.
- Currency comes from the provider when it states one (UKG); otherwise it is USD (A-31).
- `per` is one of `HOUR` `DAY` `WEEK` `BIWEEK` `SEMIMONTH` `MONTH` `QUARTER` `YEAR` `PAY_PERIOD`.

**Percentages** carry their basis and whether the scale is proven:

```json
{"percent": "5", "basis": "GROSS_PAY", "scale": "VERIFIED_POINTS", "raw": "5.0"}
{"percent": null, "basis": "UNSPECIFIED", "scale": "UNVERIFIED", "raw": "5.0"}
```

When the scale is unverified, `percent` stays null and only `raw` is given, so no consumer can
mistake a possible 500% for 5% (A-29).

**A derived value:** `{"amount": "1880.00", "currency": "USD", "derived": true, "formula": "sum(earnings[].amount)"}`

**Fields on every record:** `id`, the relationship keys (§2.1), `source` (provider, tenant, endpoints,
source IDs), `provider_extensions` and `diagnostics` (each with code, severity, field, message and a
sanitized raw value).

### 2.1 IDs and relationships

Canonical IDs have the form `{provider}:{tenant}:{entity}:{source ids}`. Each record carries the
canonical IDs of the records it belongs to.

| Record | Relationship keys | Rule |
|---|---|---|
| Company | (none) | none |
| Employee | `company_id`; `legal_entity_id` (nullable) | required; legal entity = UKG EIN, or null |
| DirectDeposit | `employee_id`, `company_id` | required |
| DeductionElection | `employee_id`, `company_id` | required |
| PayrollRun | `company_id` | required |
| PayStatement | `employee_id`, `company_id`; `payroll_run_id` (nullable) | null, with a diagnostic, when the run can't be matched uniquely |

| Entity | PrismHR source IDs | isolved source IDs | UKG Ready source IDs |
|---|---|---|---|
| Company | `clientId` | `clientId` + `legalId` | company id |
| Employee | `clientId` + employee `id` | employee `id` | account `id` |
| DirectDeposit | employee + position in `achVoucher[]` / `hsaDepositSettings[]` (no deposit ID; accounts fully masked) | deposit `id` | deposit `id` |
| DeductionElection | employee + `deductionCode` + `startDate`; loans by `loanId` | pay item `id`; garnishment `id` | deduction `id` |
| PayrollRun | `batchId` | pay group + run history `id` | payroll `id` |
| PayStatement | `voucherId` | check `id` | pay statement `id` |

**Joining a paycheck to its payroll run:**
- **PrismHR:** the voucher's `batchId` points at the run directly.
- **UKG:** pay statements are read under their payroll, so the link comes from the request path.
- **isolved:** a check carries `payrollRunNumber`, `checkDate` and its period, while run history
  carries a separate `id` and `runNumber`. We match on legal company + pay date + run number (+ pay
  group when known). A run number is never treated as a run ID. Zero or several matches mean
  `payroll_run_id = null`, with a diagnostic.

## 3. Company

| Field | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| `name`, `legal_name` | `clientName`, `legalName` | `dbaName`, `legalName` | none: no company endpoint (A-15) |
| `parent` | none | the isolved client (id, name) | none |
| `status` (`ACTIVE` `PENDING` `INACTIVE` `TERMINATING` `TERMINATED`) | `statusClass` A/P/I/C/T (documented) | `status` text | none |
| `own_tax_id`: a business FEIN, kept as returned; masked values stay masked | `federalIdNumber` (fully masked live) | `federalEIN` | none |
| `service_arrangement` | `serviceType` PEO/ASO/PAY/ASA/COR/HRN (documented) | none | none |
| `employers[]` (provider terms) | `employerId` + `altEmployer[]`; name and EIN refused (A-09) | the legal company itself | `lookup/eins`, plus EINs only payrolls name (A-60) |
| `pay_groups[]` | `getClientCodes` PGroups + `getPayrollSchedule` | `payGroups` (frequency via §6) | not available |

## 4. Employee

| Group | Fields |
|---|---|
| Identity | `identifiers[]` of {type, value}; `national_id` as {type, last4, masked_at_source} |
| Name | `first`, `middle`, `last`, `preferred`, `prefix`, `suffix` |
| Personal | `birth_date`; `gender`, `marital_status` and `ethnicity` (coded, label kept); veteran and disability statuses (including "declined"/"not specified"); `citizenship`; `preferred_language`; `emergency_contacts[]` |
| Contact | `addresses[]`, `phones[]`, `emails[]`, each typed |
| Employment | `status` (`ACTIVE` `ON_LEAVE` `TERMINATED`) and its date; `employment_type` (`FULL_TIME` `PART_TIME`); `worker_classification` (`EMPLOYEE` `CONTRACTOR_1099`); hire / rehire / start / seniority / termination dates; `termination_reason`; `flsa_exempt`; `employer_ids[]` |
| Job | `title`, `job_code`, `department`, `division`, `location`, `manager`, `supervisor`, `union`, `cost_centers[]` |
| Compensation | `pay_type` (`SALARY` `HOURLY` `COMMISSION` `DRIVER`); `pay_frequency` with `periods_per_year`; `rates[]`, each with its own `per`; `annual_pay` (as provided, or derived and flagged); `standard_hours`; `effective_date`; `history[]`, each entry with its own source ID |
| Tax setup | kept in `provider_extensions` for v1 (§10) |

| | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| IDs | response `id` (the request parameter is `employeeId`); `client.clientEmployeeId`; `client.clockNum` | `id`; `employeeNumber`; `timeclockId`; `uniqueId` | `id` (account); `employee_id`; `external_id` |
| SSN | `compensation.ssn` (masked live); `person.cobraSSN` is also sanitized | `ssn` is null live; last 4 from `checks[].employeeSSN` (A-50) | `social_security` and `national_id_numbers[]`, returned in full live and reduced to last 4 |
| Status | `client.statusClass` A/L/T (documented), plus the client status code and label | `employmentStatus`: "Active"/"Terminated" only when `/statuses` shows it as an implied system status (A-48); others `UNMAPPED` with the label | `status`: undocumented, but consistent with `dates.terminated` live |
| Type | `client.typeClass` F/P (documented filter values) | `employmentCategoryCode`: customer code, `UNMAPPED` | pay-info `employee_type`: tenant label, `UNMAPPED` |
| Worker class | `client.employee1099` (independent of `payMethod`) | `payType` "1099" gives `CONTRACTOR_1099` and pay type `UNMAPPED` | none |
| Pay | `payMethod` S/H/C/D. `salary` is per pay period (A-20). `hourlyPay` is per hour. `hourlyPayRate` is per `hourlyPayPeriod` (live `A` = annual, A-19). | `payType`; `hourlyRate` per hour; `perPaySalary` per pay period; `annualSalary` | compensation `amount` per `amount_period`; `hourly_pay`; `time` in ms per `time_period`; `num_pp_in_year` |

## 5. DirectDeposit

**Fields:**
- `purpose`: `NET_PAY` or `HSA`.
- `funding`: `EMPLOYEE` or `EMPLOYER`, for HSA only.
- `account`: type, routing number, last 4, bank name and routing type.
- Allocation: `method`, `amount`, `percent` (§2), `limit`.
- `sequence`, `is_remainder`, `status`.
- `prenote`: status, sent date and expiration date.
- `effective_from` and `effective_to` (§6).
- `frequency`, `applies_to_pay_types` and `currency`.

Methods are mapped per **full source field**:

| Canonical method | Prism `achVoucher.method` | Prism `hsaDepositSettings.method` | isolved | UKG `calc_method.type` |
|---|---|---|---|---|
| `FIXED_AMOUNT` | F | F | `amount` set | FLAT_AMOUNT ("Flat Amount") |
| `FIXED_AMOUNT_SKIP_IF_INSUFFICIENT` | FS | FS | none | none |
| `PERCENT_BASE_UNSPECIFIED` | P | P | `percent` set | none |
| `PERCENT_OF_GROSS` | none | none | none | GROSS_EARNING ("% Of Gross Earnings", from a docs sample) |
| `PERCENT_OF_NET_AFTER_FIXED` | PN | none | none | none |
| `PERCENT_OF_NET_AFTER_TAXES` | none | PN | none | none |
| `REMAINDER` | B | B | `sequenceNumber` 0 ("0 = Net Pay") | FULL ("Entire/Remainder") |
| `UNMAPPED` | other | other | none | NET_PAY and DIRECT_DEPOSIT_PER_OF_REMAINDER: no documented meaning; raw type and label kept (A-26) |

| Canonical account type | Source |
|---|---|
| `CHECKING` | isolved "Checking"; UKG CHECKING; Prism HSA HE/HC ("to Checking") |
| `SAVINGS` | Prism S; isolved "Savings"; UKG SAVINGS; Prism HSA HES/HCS ("to Savings") |
| `CHECKING_OR_PAY_CARD` | Prism C only: documented as "checking account or pay card" |
| `INSTANT_PAY` | Prism IP |
| `PAPER_CHECK` | UKG RESERVE_LIVE_CHECK, which reserves a paper check rather than naming an account |

- **Prism HSA funding:** HE/HES are employee-funded and HC/HCS are company-funded (documented).
- **Status:** Prism D/I/P and isolved "Active"/"Inactive" map directly. UKG status is derived from
  `active` plus the date span at `as_of` (§6).

## 6. Dates, spans and frequencies

- **Format:** dates are ISO `YYYY-MM-DD`. isolved date-times become dates; any non-midnight time is
  kept in the raw value, with a diagnostic.
- **UKG span convention (`Foundations.html`):**
  - "beginning of time" = 1900-01-01 and "end of time" = 3000-01-01;
  - effective dates are **inclusive** and expiration dates **exclusive**.

  Only those two documented dates become `null` (open-ended), with the raw value kept. Other
  far-off dates are kept as real dates with an info diagnostic: 9999-12-31 and 1900-12-31 in doc
  samples, and 2099-12-31 live (A-25). A UKG record is active at `as_of` when
  `from <= as_of < to`.
- **Prism and isolved** don't document span semantics. Their end dates are treated as inclusive,
  and that assumption is noted (A-25).
- **Pay frequency:** isolved resolves it through the Frequencies lookup by *description*, using a
  fixed table: Weekly = 52, Bi-Weekly = 26, Semi-Monthly = 24, Monthly = 12, Quarterly = 4,
  Annually = 1, and "N Pay Periods Per Year" = N. The lookup ID is never used as a count (A-27).
  Prism uses `payPeriod` codes; UKG uses `num_pp_in_year`.

## 7. DeductionElection (setup)

**Fields:**
- `code`, `label`, `category`, `tax_treatment` and `catch_up`.
- `calculation`: {`method`, `basis`, `value`, `rounding`, `raw`}.
- `limits`: per period, maximum, and the maximum's basis.
- `frequency`, `effective_from` and `effective_to`.
- `employer_match`, `arrears_tracking` and `mandatory`.
- `benefit_plan_id` and `loan_or_garnishment_id`.
- Garnishment details and loan details.

**Category and tax treatment:**

| Category / tax treatment | PrismHR `deductionType` (documented) | isolved `systemBenefitType` |
|---|---|---|
| `RETIREMENT` / `PRE_TAX` | K; KC with `catch_up` | 401(k), treatment `UNSPECIFIED` |
| `RETIREMENT` / `POST_TAX` | KE | none |
| `RETIREMENT` / `ROTH` | KR; KCR with `catch_up` | none |
| `RETIREMENT_LOAN` | KL | none |
| `SECTION_125` / `PRE_TAX` | C | Medical, Dental and Vision "Pre-Tax 125" |
| `FSA` | F | FSA Medical; FSA Dependent Care |
| `HSA` | none | Health Savings Account |
| `POST_TAX_BENEFIT` / `POST_TAX` | P | none |
| `VOLUNTARY` | V | system pay item "Voluntary Deduction" |
| `GARNISHMENT` | G | `/garnishments` |
| `LOAN` | L | none |

**Calculation methods.** Prism documents 29 calculation methods in
`DeductionCodeDetail.calculationMethod`. Each one keeps its basis:

| Canonical method / basis | Prism codes |
|---|---|
| `FIXED_AMOUNT` | F |
| `PERCENT` / `GROSS_PAY`, `GROSS_EARNINGS`, `STRAIGHT_PAY`, `PAY_RATE`, `RETIREMENT_EARNINGS`, `EARNINGS`, `GROSS_EARNINGS_LESS_DEDUCTIONS`, `CERTIFIED_JOB_EARNINGS` | PG, PE, PS, PPR, PR, PET, PGD, PCE |
| `PERCENT` / `PAY_RATE` or `PRIOR_MONTH_PAY_RATE`, rounded to the dollar | PPRD, PPRM |
| `PER_TEN_THOUSAND` / `GROSS_PAY`, `GROSS_EARNINGS`, `STRAIGHT_PAY`, `RETIREMENT_EARNINGS` | PXG, PXE, PXS, PXR |
| `RATE_PER_HOUR` / `HOURS_WORKED`, `HOURS_PAID`, `HOURS_PAID_SELECTED_CODES`, `CERTIFIED_JOB_HOURS`, `UNION_JOB_HOURS`, `UNION_PROJECT_HOURS` | R, RP, RPS, RC, RUJ, RUP |
| `RATE_TABLE` | RT |
| `PROVIDER_RULE` (garnishment, retirement plan, union dues, Ohio taxes, in/out) | G, K, U, UF, OH, OHSERS, IO |

**Other providers:**
- **isolved** pay items give `Amount`, `Percent` or `Rate` with no basis, so the basis is
  `UNSPECIFIED` and the percent scale is unverified.
- **UKG** `ee_calc_method.method.type` is an open string, so it stays `UNMAPPED`, with its
  `display_name` kept as the label.

**UKG support.** The converter supports UKG's documented setup endpoints (`#/schemas/132`, `#/schemas/133`)
and is tested on synthetic data. Only the live demo tenant returns 404 (A-12). That's a tenant gap,
not a provider one.

## 8. PayrollRun and PayStatement

**PayrollRun:**
- `pay_date`, run and processed dates, `type`, `status`.
- `pay_groups[]`, each with its own period start and end, weeks worked and deduction period. Prism
  gives periods per pay group (`BatchByDateResponse-BatchList-PayGroup`).
- `period` for providers with one period per run, and `legal_entity_id`, the EIN the run is for
  (UKG).
- Types are `REGULAR` `SPECIAL` `MANUAL` `VOID` `ADJUSTMENT` `CORRECTION` `HISTORICAL_IMPORT`.
- Statuses are `OPEN` `CLOSED` `SUBMITTED` `COMPLETED` `NOT_PROCESSED` `FAILED`, always with the raw
  value (A-21).

**PayStatement:**
- **Header:** pay date, period, check number, type, status, plus void and reissue details.
- **Totals:** `gross_wages`, `gross_pay`, `net_pay`, employee and employer taxes, deductions, and
  employer contributions. Each is either provided or derived and flagged. The two gross figures mean
  the same thing for every provider (A-54):
  - `gross_wages` is every earning counted in gross, non-cash ones included;
  - `gross_pay` is the part actually paid: gross wages minus non-cash earnings (`NON_CASH_FRINGE`,
    `REPORTED_TIPS`, and `MEMO` lines counted in gross).
- **`earnings[]`:**
  - code, label and `kind` (`EARNINGS` `REIMBURSEMENT` `NON_CASH_FRINGE` `REPORTED_TIPS` `MEMO`): how
    the line is paid;
  - `category`, what an earnings line pays for (A-67): `REGULAR` `OVERTIME` `DOUBLE_TIME`
    `SHIFT_DIFFERENTIAL` `VACATION` `SICK` `HOLIDAY` `PAID_TIME_OFF` `BONUS` `COMMISSION` `TIPS`
    `SEVERANCE` `PENSION` `WORKERS_COMPENSATION` `NON_EMPLOYEE_COMPENSATION` `OTHER`. Null on lines
    whose kind already says it all (reimbursement, fringe, tips, memo). `UNMAPPED`, with the earning
    code as raw, where the provider doesn't classify the code;
  - `in_gross`: whether the provider counts the line in gross wages (Prism: every line, A-32;
    isolved: every non-memo line, A-28);
  - `quantity` (value with unit `HOURS`/`UNITS`/`UNKNOWN`) and `hours_worked`;
  - rate, amount, line date range and allocations.
- **`taxes[]`:** code, label, `paid_by`, amount, and employee and employer wage bases kept separate.
  - `type` (A-68): `FEDERAL_INCOME` `SOCIAL_SECURITY` `MEDICARE` `ADDITIONAL_MEDICARE`
    `FEDERAL_UNEMPLOYMENT` `STATE_INCOME` `STATE_UNEMPLOYMENT` `STATE_DISABILITY` `STATE_PAID_LEAVE`
    `LOCAL_INCOME` `OTHER`;
  - `state`: the USPS code of a state-level tax, when the provider's code or description names it.
- **`deductions[]`:** code, external ID, label, category, and employee and employer amounts.
- **`employer_contributions[]`.**
- **`benefit_details[]`:** premium, employee and employer amounts, coverage period. These are
  informational and never added into totals.
- **`retirement`:** pre-tax, catch-up, Roth, post-tax, employer match, non-elective, safe-harbor and
  loan amounts (Prism).
- **`payments[]`:** `DIRECT_DEPOSIT` or `CHECK`, amount, last 4.

| | PrismHR voucher | isolved check | UKG pay statement |
|---|---|---|---|
| Gross wages | `totalEarnings` (it includes non-cash classes, A-32) | `grossWages` | **derived** from the lines: no total in the API |
| Gross pay | **derived**: `totalEarnings` − non-cash lines (A-54) | `grossPay` (= `grossWages` − group-term life, A-28) | **derived** only when every line's kind is known |
| Net | `netPay` | `netPay` | **derived** from payments |
| Earning lines | `earning[]` **and** `otherEarningsDetail[]` (gross = earn + other) | `earnings[]` (`check*` bucket, A-28) | `earnings[]` |
| Quantity | `hoursUnits`, which is "hours or units paid": the unit comes from the pay code's documented `payReason` H/U, else `UNKNOWN`. Plus `hoursWorked` (A-38). | `checkHours` and `checkUnits` | `hours` in ms, converted to hours (A-24); `quantity` unit `UNKNOWN` |
| Line amount | `payAmount` = quantity × `unitRate` (A-18) | `checkDollars` | `ee_amount` |
| Earning kind | `payClass` E/R/F/RT/M (documented) | `isMemoEarning`, else the client pay item's system earning (A-53) | `type_name`: Earning, Earning (Fringe), Reimbursement (A-58) |
| Earning category | the pay code's `talxPayType` (documented; blank live), or `rateClass` D; else `UNMAPPED` for review (A-67) | the client pay item's system earning, else its "Leave Accrual" benefit type (A-67) | none: the tenant's codes, `UNMAPPED` for review (A-67) |
| Taxes | `employeeTax[]`, `companyTax[]` | `taxes[]` + `isEmployeeTax` | `taxes[]` with `ee_*` and `er_*` amounts and wage bases |
| Tax type | federal codes `00-NN`; state `<state>-<tax number>`, local `<locality>-<tax number>`, by tax number (A-68) | the system tax description: "FEDERAL WH", "<state> WH", "<state> SUI ER" (A-68) | documented codes FIT, FICA (OASDI), MEDI, FUTA; `SIT:<state>`, `SUTA:<state>` (A-68) |
| Deductions | `deduction[]` (`deductType`), `otherDeduction[]` | `deductions[]`, `garnishments[]` | `deductions[]`: code, external ID, name |
| Employer contributions | `employerContributions[]` | `benefits[].checkEmployerContribution` | `deductions[].er_amount` |
| Payments | `checkAmt` + `directDeposit[]` | `checkAmount` + `directDeposits[]` | `payments[]` (`type_name` "Check" / "Direct Deposit"; "Fringe" rows balance non-cash pay and are not payments, A-58) |

**Checks, reported and never "fixed":**
- gross wages = the sum of earning lines counted in gross;
- gross wages − non-cash earnings = gross pay, when both are provided;
- gross pay − employee taxes − deductions = net, when the statement has line items;
- payments = net.

A derived total is never checked against the lines it was derived from.

A failed check becomes a `RECONCILIATION_MISMATCH` warning; the totals stay as the provider sent them.

## 9. Field dispositions, sensitive data, drops and testing

**Explicit dispositions for fields the audit raised:**

| Field | Disposition |
|---|---|
| Prism emergency contacts, citizenship status (Z01–Z04, documented), preferred language | mapped (§4 Personal) |
| Prism and isolved veteran / disability answers, including declined and not specified | mapped as coded values, label kept |
| Prism skills/education, transfer history, events, property; isolved organizations, labor and misc datasets | `provider_extensions` |
| Prism deduction arrears, mandatory flag, benefit plan, loan/garnishment reference | mapped (§7) |
| Prism deduction rate table/tier and linked ACH account | `provider_extensions` |
| Prism batch per-group periods, weeks worked, deduction period | mapped (§8 `pay_groups[]`) |
| Prism voucher `otherEarningsDetail`, retirement breakdown, benefit lines | mapped (§8) |
| isolved deposit `frequency` (required), pay item schedule override and calc parameters | mapped |
| isolved check benefit lines, labor allocations, reissue details | mapped (§8) |
| UKG multiple national IDs and managers, EIN and primary-account links, cost centers | mapped (sanitized) |
| UKG deposit frequency, prenote dates, routing type, currency | mapped (§5) |
| UKG deposit arrearage behavior | `provider_extensions` (enum values without documented meanings) |
| UKG pay-info pay grade, shift premium, job change, benefit eligibility | `provider_extensions` (eligibility codes are kept raw) |
| UKG pay-statement line dates, batches, allocations, wage bases, payment types | mapped (§8) |
| Year-to-date and accumulator buckets; workers' comp; GL distributions | `provider_extensions` |

A generated `docs/FIELD_COVERAGE.md` will list every response field's disposition.

**Sensitive data.** A registry of sensitive source fields, plus a pattern sweep over everything
else, sanitizes these:
- SSNs: Prism `ssn` and `cobraSSN`; UKG `social_security`, `national_id_numbers[]`,
  `social_insurance`, `national_insurance` and `bsn`;
- bank account numbers: Prism `accountNum` (deposits, HSA, vouchers); isolved `accountNumber` and
  check `account`; UKG `account_number` and pay-info `bank_account_number`.

Sanitizing keeps at most the last 4 digits, and never invents digits for values that arrived masked.

**Dropped (never requested or not kept):**
- the Prism `Health` option (medical data);
- isolved profile pictures, document contents and I-9 documents;
- UKG `photo_href`, a signed link that works as a credential.

**Testing notes:**
- Fixtures are generated from known facts and validated against the provider schema. Live aliases
  such as Prism's `payrollVoucher` are first translated back to the documented name, so the
  contents get validated too, not just accepted as extra properties. The converter receives the
  live alias form (A-43).
- All inputs are parsed with exact decimals.

## 10. Scope decisions

1. **Tax withholding setup** is kept in `provider_extensions`, not normalized (A-34).
2. **Customer-configured labels** stay `UNMAPPED` with the label kept, until a mapping file classifies
   them (A-35, A-65).
3. **Output** is JSON per record type plus a SQLite database with the same records linked by ID, each
   with its provenance (A-36, A-71).
