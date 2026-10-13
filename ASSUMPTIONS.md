# Assumptions, decisions and limitations

Each entry has four parts: **issue**, **evidence**, **decision** and **why**.

- **Spec evidence** is a JSON pointer into the files under `contracts/`. These abbreviations are used:
  - **Prism** = `contracts/prismhr/openapi/prismhr-2025.09.openapi.json`
  - **isolved** = `contracts/isolved/openapi/isolved-v6.swagger.json` (the primary snapshot only)
  - **UKG** = `contracts/ukg-ready/reference-schemas.json`, plus HTML pages under `contracts/ukg-ready/reference-docs/`
- **Live evidence** comes from read-only requests to the demo tenants on **2026-10-12**, plus a second
  UKG fetch on **2026-10-13** (A-07). The raw
  responses stay on the machine that fetched them and are never committed, so this file quotes counts
  and code values only.

Status: first draft, written during discovery. Entries are added as mapping decisions are made.

## Repository and process

### A-01 Fresh repository with no link to the organizer's repository
- **Issue:** the submission must be our own repository.
- **Decision:** start a new git history whose first commit is the organizer's starter files, unchanged.
  There is no fork, no upstream remote and no shared history.
- **Why:** the submission is clearly separate, and nothing can ever be pushed to the organizer's
  repository by mistake. `tests/test_reference_integrity.py` still passes, which proves `contracts/`
  is byte-identical.

### A-02 Replacing the starter scaffold (done)
- **Issue:** the optional starter does three things that get in the way:
  - it refuses isolved and UKG through a distribution "readiness" gate;
  - `ENTITIES` has no deposits or deductions;
  - `tests/test_starter.py` asserts that the adapters stay unimplemented.
- **Decision:**
  - `src/normalization/__main__.py` is now the project's CLI (`demo`, `normalize`, `fetch`,
    `schema`).
  - The stub `adapters/` became the converters under `providers/`, and `test_starter.py` became the
    real tests.
  - `references.py` stays, because `test_reference_integrity.py` imports it. Its one changed line
    imports the provider list from `providers/` instead of the removed adapters.
  - `contracts/` and `test_reference_integrity.py` are untouched.
- **Why:** the gate checks *distribution metadata*, not data correctness. The organizer approved
  sharing the reference pack with candidates (README, "Reference status").

### A-03 Stack
- **Decision:** Python 3.11+ with Pydantic v2 for the canonical model (exported to JSON Schema),
  `jsonschema` to validate fixtures against the provider schemas, httpx for live calls, and pytest.
- **Why:** typed models with schema export make the canonical format checkable by anyone, in any language.

## Live access

### A-04 Read-only, scope-guarded live access
- **Issue:** the demo tokens are write-capable. The Prism and isolved tokens also reach companies
  beyond the demo ones (sign-in service README).
- **Decision:** every live request passes `src/normalization/live/scope.py` before it is sent:
  - GET only, on the `/signin` base URL host;
  - allowlisted endpoints only;
  - only the demo company IDs that `/signin` returned.
- **Hardening after the audit:**
  - Redirects are never followed automatically: each request sets `follow_redirects=False`, and our
    own redirect loop re-checks every hop.
  - A redirect from the sign-in service is refused outright, because following it would resend the
    API key.
  - Saved captures, the index and log lines are scrubbed of the API key, the session's tokens and
    embedded signed tokens. Credential-bearing headers are dropped.
  - Numbers are kept exactly as the provider wrote them (`normalization.exactjson`).

  Offline tests reproduce each attack and fail if the matching fix is removed.
- **Why:** these are real provider UAT systems, so the code must make a mistake impossible, not merely unlikely.
### A-05 One exception: Prism employer lookups
- **Issue:** `system/v1/getEmployerDetails` is not keyed by client. Called without an `employerId`,
  it lists every employer in the tenant.
- **Decision:** allow it only for employer IDs that a demo client's own `getClientMaster` response
  references (`employerId`, `altEmployer[]`). A request without an `employerId` is always refused.
- **Evidence and outcome:** the 25 demo clients reference employers 1, 5, 10, 20, 125 and 138. All
  six lookups returned 403 (A-09).

### A-06 Live data is never committed; tests use synthetic data
- **Decision:** responses go to `.discovery/`, which is gitignored. Fixtures are generated from a
  seed and validated against the provider schemas.
- **Why:** the README forbids committing downloaded records. Separately, live responses contain full
  SSNs (UKG) and bank account numbers (isolved).

### A-07 What was sampled
- **PrismHR:** 4 of 25 clients, 51 employees, 420 vouchers from 33 payroll batches (2015–2026), and
  the master records of all 25 clients.
- **isolved:** client 4046, both legal companies (5797 and 5806), 30 employees, 430 checks from the
  check list (15 also fetched in detail), and 231 payroll runs from run history (8 fetched in detail).
- **UKG Ready:** company 33704016, 15 employees, 89 payrolls listed (10 fetched in detail), and 28
  pay statements listed (22 fetched in detail).
- **UKG, second fetch (2026-10-13):** the first crawl sampled the first 15 employees rather than the
  paychecks' owners, so 27 of its 28 statements belonged to employees outside the sample. The crawl now
  samples paycheck owners first, as the isolved crawl does. The second fetch found 89 payrolls and 61
  pay statements, and 36 of those statements belong to the 15 sampled employees; the others exceed the
  limit. Every UKG claim below holds on both fetches unless it says otherwise.
- **Limitation:** codes that never appeared in these samples are mapped from the documentation only.

## Data that is unavailable

### A-08 PrismHR garnishment details are refused
- **Evidence:** `deductions/v1/getGarnishmentDetails` returns HTTP 403 with "this user session is not
  authorized for the method specified" for every employee.
- **Decision:** garnishments come only from deduction codes of type `G` and from voucher deduction
  lines. Docket, payee and limit details are a documented gap.

### A-09 PrismHR employer names and EINs are refused
- **Evidence:** `system/v1/getEmployerDetails` returns 403 for all six referenced employer IDs.
- **Decision:** a company's `employers[]` keeps the employer IDs only, and the name and EIN stay null.

### A-10 isolved's payroll list and "corestream" deduction endpoints are refused
- **Evidence:** these return 401 "Authorization has been denied for this request", even immediately
  after a fresh sign-in:
  - `/employees/{e}/payroll`;
  - `/api/corestream/.../employees/{e}/deductions`;
  - `/api/corestream/.../paygroups/{pg}/payrolls/{id}`.
- **Decision:** deduction setup comes from `/employees/{e}/payItems` (570 deduction items live), and
  payroll deductions come from check details.
- **Why:** the alternative endpoints are documented and readable, so nothing is lost.

### A-11 isolved has only historical, imported payroll
- **Evidence:**
  - Pay group 7612 has 231 runs. 36 are "Completed Payroll Run" (all "Data Conversion", 2018) and
    195 are "Payroll Not Processed".
  - The other pay groups return 404 (no history).
  - The legal-level check list returns 430 checks, all from "Data Conversion" runs. The 15 fetched
    in detail are all type "Adjustment".
- **Decision:** normalize these as they are, with run type `HISTORICAL_IMPORT`. Synthetic fixtures
  cover regular runs.

### A-12 UKG deduction setup: this tenant returns 404; the provider documents it
- **Evidence:** UKG documents employee deduction setup in `#/schemas/132` (list) and `#/schemas/133`
  (detail): frequencies, annual limits, calculation methods and dates. The live demo tenant returns
  404 "Unresolvable URL" for all 15 employees.
- **Decision:** the UKG converter supports the documented endpoints and is tested on synthetic data.
  For this tenant, no UKG `DeductionElection` records are produced, and the gap is reported.
  Deductions still appear on pay statements.
- **Setup amounts:** `annual_max_amount` and the calculation `amount` fields are typed integer, and
  nothing says whether they are dollars or cents. They stay raw in `provider_extensions`, with an
  `AMOUNT_UNIT_UNVERIFIED` diagnostic. The calculation method is an open string, so it stays
  `UNMAPPED` with its `display_name`.
- **Why:** a tenant's missing endpoint is a fact about the tenant, not about UKG. The converter
  shouldn't be limited by one demo account.
### A-13 UKG payroll runs are all OPEN
- **Evidence:**
  - All 89 payrolls from 2025-09-12 to 2027-06-04 have status `OPEN`.
  - Pay statements exist inside some past runs: 22 found, all `OPEN`.
- **Decision:** normalize them, with a diagnostic that the amounts are not finalized.

### A-14 UKG's deprecated direct-deposit endpoint still works
- **Evidence:** the docs show the endpoint was deprecated 2023-04-13, and enforcement for "new
  customers" starts 2026-01-29 (`Deprecation and Versioning.html`). Live, all 15 calls returned 200.
- **Doc contradiction:** the endpoint page lists `X-End-of-Support-Timeline` as a required *request*
  header (default 2026-01-29), while `HTTP Headers.html` describes it as a *response* header.
- **Decision:** send the documented default and record what happens. It can stop working at any
  time; that limitation is documented.

### A-15 UKG has no company details endpoint
- **Decision:** the UKG company's name and address stay null. Its EINs come from `lookup/eins`.

## Places where live data differs from the specs

### A-16 PrismHR response keys differ from the spec
- **Evidence:**
  - Live `getPayrollVoucherForBatch` returns `payrollVoucher`; Prism
    `#/components/schemas/PayrollResponseWithPagination/properties/payrollVouchers` documents
    `payrollVouchers`.
  - Live `getPayrollSchedule` returns `clientPayrollSchedule`; the spec documents
    `clientPayrollSchedules`.
- **Decision:** the converters accept both spelling forms, and fixtures include both.

### A-17 PrismHR loan dates are YYYY-MM-DD, not the documented YYYY-DD-MM
- **Evidence:** Prism `#/components/schemas/EmployeeLoanDetails/properties/startDate` (and the
  related loan fields) say "YYYY-DD-MM". Live payment dates include `2014-10-17`, which is impossible
  as YYYY-DD-MM (there is no month 17), and every payment date falls on a Friday.
- **Decision:** parse them as YYYY-MM-DD, and add a diagnostic if a value is ambiguous and conflicts.

### A-18 PrismHR earning `payAmount` is the line total
- **Evidence:** Prism `#/components/schemas/Earning/properties/payAmount` says "pay per hour or unit",
  and `unitRate` is undocumented. Live, `hoursUnits × unitRate = payAmount` on **465 of 465** lines.
- **Decision:** the line amount is `payAmount` and the rate is `unitRate`.

### A-19 PrismHR pay-rate basis `A` is undocumented; it behaves as annual
- **Evidence:** Prism `#/components/schemas/Compensation/properties/hourlyPayPeriod` documents
  H/W/B/S/M/Y. Live, 18 employees have `A`, and on all 18 `hourlyPayRate` equals `annualPay`. The
  documented `Y` behaves the same way (1 of 1).
- **More evidence:** the pay-rate history schema documents `A` as "annually"
  (`#/components/schemas/PayRate/properties/payPeriod`).
- **Decision:** map `A` to per `YEAR`, keep the raw value, and add an info diagnostic.

### A-20 PrismHR `salary` is per pay period
- **Evidence:** Prism `#/components/schemas/Compensation/properties/salary` documents it.
  - Live, `salary × pay periods per year = annualPay` for all 29 salaried employees (W=52, B=26, M=12).
  - For all 22 hourly employees, `annualPay = hourlyPay × 2080`.
- **Decision:** `salary` is mapped as a rate per `PAY_PERIOD`. `annualPay` is kept as a
  provider-calculated figure. For hourly employees it is an assumed 2080-hour year, not a contract
  amount, and is labeled that way.

### A-21 PrismHR batch codes that the spec doesn't document
- **Evidence:** Prism `#/components/schemas/BatchList/properties/batchType` documents R/M/S/V.
  - Live, an empty `batchType` also appears.
  - `batchStatus` values (`COMP`, `TS.READY`, `TS.ENTRY`, `INITFAIL`) have no documented meanings.
- **Decision:**
  - An empty batch type maps to `UNMAPPED`.
  - `COMP` maps to `COMPLETED`, because every voucher in a `COMP` batch has status `PRNT` (printed).
  - Other statuses stay `UNMAPPED`, with the raw value kept.

### A-22 PrismHR voucher fields the spec doesn't document
- **Evidence:** the live vouchers have `isManualCheck` and `hsaPeoMatch`, which are not in the
  `PayrollVoucher` schema.
- **Decision:** keep both in `provider_extensions`.

### A-23 Masking differs by provider; our output sanitizes everywhere
- **Evidence:**
  - Prism SSNs come back fully masked (`***-**-****`), and so do its bank account numbers (all
    asterisks, no last 4). Birth dates come back **unmasked**, although
    `#/paths/~1employee~1v1~1getEmployee/get/description` says they are masked by default.
  - isolved returns full direct-deposit account numbers, and no SSN from this endpoint.
  - UKG returns full SSNs. Its employee `photo_href` links each carry a signed token.
- **Decision:**
  - SSNs and bank account numbers keep at most their last 4 digits **everywhere** in the output:
    canonical fields, `provider_extensions`, raw values and diagnostics. Values the provider already
    masked yield no last 4 (nothing is invented).
  - A registry of sensitive source fields, plus a pattern sweep, enforces this. The registry includes
    Prism `cobraSSN` and UKG pay-info `bank_account_number`.
  - `photo_href` is dropped. Birth dates are kept as employee data.
- **Why:** keeping fields "verbatim" in `provider_extensions` would otherwise undo the masking.
### A-24 UKG pay-statement hours are milliseconds
- **Evidence:**
  - UKG `#/schemas/364` types earnings `hours` as an integer with no unit. Live, all 23 earning lines in
    the first fetch that have both hours and a rate satisfy `(hours ÷ 3,600,000) × base_rate =
    ee_amount`, and none satisfies `hours × base_rate`. Milliseconds are also documented elsewhere in
    the same API (compensation `time`, pay-info `standard_work_day`).
  - In the second fetch, 67 of 71 such lines satisfy it. The other 4 are all overtime (code "OT"), where
    `ee_amount = 1.5 × hours × base_rate`. So `base_rate` is the employee's base hourly rate, and premium
    lines multiply it.
- **Decision:**
  - Hours are converted, with the raw value kept and the formula recorded.
  - `base_rate` becomes the line's `rate` only where hours × base_rate = amount on that line. Otherwise it
    stays raw in `provider_extensions`, with a `BASE_RATE_NOT_LINE_RATE` info diagnostic giving the
    multiple, because a canonical rate must multiply out to the amount.

### A-25 Open-ended dates and span boundaries
- **Evidence:** UKG `reference-docs/Foundations.html` ("Conventions related to time") documents
  "beginning of time" = **1900-01-01** and "end of time" = **3000-01-01**. It also says effective
  dates are inclusive and expiration dates exclusive. 9999-12-31 and 1900-12-31 appear only in doc
  samples, and 2099-12-31 appears live (every UKG deposit).
- **Correction:** an earlier draft (and the project brief) called 9999-12-31 and 1900-12-31
  "documented sentinels". They are not.
- **Decision:**
  - Only 1900-01-01 and 3000-01-01 become `null` (open-ended), with the raw value kept, and only on
    UKG span fields.
  - Other far-off dates are kept as real dates with an info diagnostic.
  - UKG spans are evaluated as `from <= as_of < to`.
  - Prism and isolved document no span semantics, so their end dates are treated as inclusive. This
    is an assumption, noted in diagnostics.
### A-26 UKG direct-deposit methods: map only what is labeled
- **Evidence:** UKG `#/schemas/137` lists the `calc_method.type` values with no descriptions. The
  cached response samples label `FULL` "Entire/Remainder", `FLAT_AMOUNT` "Flat Amount" and
  `GROSS_EARNING` "% Of Gross Earnings". Live data showed only `FULL` ("Entire/Remainder").
  `NET_PAY` and `DIRECT_DEPOSIT_PER_OF_REMAINDER` have no label anywhere.
- **Decision:**
  - `FULL`, `FLAT_AMOUNT` and `GROSS_EARNING` map to `REMAINDER`, `FIXED_AMOUNT` and
    `PERCENT_OF_GROSS`.
  - `NET_PAY` and `DIRECT_DEPOSIT_PER_OF_REMAINDER` map to `UNMAPPED`, unless the record's own
    `display_name` states the basis.
- **Why:** enum names are the provider's words but carry no definition. Labels are evidence; names
  alone are not.
### A-27 isolved pay frequency: resolve by description, not by ID
- **Evidence:**
  `#/definitions/AOS.PayrollOffice.RestAPI.Models.LookupFrequencyModel/properties/id` defines the ID
  only as a "Unique Object Id".
  - Live `/api/lookup/Frequencies` has descriptions such as Monthly, Semi-Monthly, Bi-Weekly, Weekly
    and "N Pay Periods Per Year".
  - The live IDs happen to equal those counts (12, 24, 26, 52), but nothing promises that.
- **Decision:** `payFrequency` is resolved through the lookup, and the *description* maps through a
  fixed table: Weekly = 52, Bi-Weekly = 26, Semi-Monthly = 24, Monthly = 12, Quarterly = 4,
  Annually = 1, "N Pay Periods Per Year" = N. The ID is never used as a count. Unknown descriptions
  map to `UNMAPPED`.
### A-28 isolved check buckets and its two gross figures (resolved)
- **Evidence:** for each check, the spec gives `check*`, `current*`, `ptd`, `mtd`, `qtd`, `ytd` and
  `ftd` amounts without explaining them. On all 15 live check details:
  - `checkDollars` equals `currentDollars` on every line;
  - `grossWages` equals the sum of non-memo earnings;
  - `grossPay` − employee taxes − deductions − garnishments = `netPay`;
  - `checkAmount + directDepositAmount = netPay` (also on all 430 rows of the check list).

  `grossPay` is a little below `grossWages` (by $0.37 to $9.92). The gap is exactly the check's
  group-term life lines on **15 of 15**: earnings whose client pay item has system benefit type
  "Group Term Life". isolved's own system earning describes that item as "Group Term Life - taxable
  amount over $50K": imputed income that is taxed but never paid. All 420 listed checks with a gap
  have `grossPay` below `grossWages`; the other 10 have none.
- **Decision:** `check*` is "this paycheck". `gross_wages = grossWages` and `gross_pay = grossPay`,
  which match the canonical meanings exactly (A-54). Each paycheck is checked for
  `gross wages − non-cash earnings = gross pay`.

## Unresolved, and how we handle it

### A-29 Percent scale (5 vs 0.05)
- **Evidence:**
  - No live direct deposit uses a percentage: Prism is all method B, isolved uses fixed or net
    accounts, and UKG is all `FULL`.
  - isolved "Percent" parameters are all 0.0.
  - Prism deductions with `usePercent = true` have amounts 3.0 and 12.0. A fraction scale would mean
    300% and 1200% of pay, which is impossible.
- **Decision:**
  - Prism deduction percents are verified percentage points: `scale: VERIFIED_POINTS`.
  - Every other percent keeps its raw value with `scale: UNVERIFIED` and `percent: null`. No
    converted number is published.
  - Synthetic fixtures cover percent allocations.
- **Why:** a warning next to a possibly wrong number still lets a consumer use the wrong number.
  Withholding the conversion makes the uncertainty impossible to miss.
### A-30 Company is the business, not the legal employer
- **Evidence:** Prism `#/components/schemas/ClientMaster/properties/serviceType` (PEO, ASO, ...) and
  `.../employerId` ("employer ID to which to assign this client's employees") are documented
  separately from `federalIdNumber`. Across the 25 live clients (18 PEO, 5 ASO, 2 COR):
  - employer 5 is shared by PEO, ASO and COR clients;
  - two ASO clients' employer IDs equal their own client IDs;
  - `federalIdNumber` is masked (23 clients) or empty (2).
- **Decision:** a company is the business the employees work for. Service arrangement, assigned
  employers and the company's own tax ID are separate fields, and none is labeled "employer of record
  for taxes".
- **Why:** the data cannot tell us who files the taxes, so we record what each provider says, in its own terms.

### A-31 Currency
- **Decision:** UKG states its currency (USD), so it is used as given. Prism and isolved state none,
  and amounts are recorded as USD.
- **Why:** both are US payroll systems with federal and state tax lines. The assumption is applied in
  one place and is easy to change.

### A-32 PrismHR gross and net reconcile from the line items (resolved)
- **Evidence:** across 420 live vouchers:
  - `totalEarnings = sum(earning[].payAmount) + sum(otherEarningsDetail[].otherEarnAmount)` on
    **420 of 420**.
  - The summary fields are the unreliable part: `otherEarnAmount` leaves out "Fringe" lines on 64
    vouchers, and `earnAmount` differs from its lines on 23.
  - Net pay reconciles on **420 of 420** once non-cash pay is excluded:
    `gross - non-cash earnings - employee taxes - deductions = netPay`. Non-cash means pay classes
    F (non-cash fringe), M (memo) and RT (reported tips), documented in
    `#/components/schemas/ClientCodes-PayCode/properties/payClass`. Such pay is taxed (it sits inside
    federal taxable wages) but not paid out.
- **Decision:** `totalEarnings` is gross *wages*, since it includes the non-cash classes. Gross pay
  is derived as `totalEarnings` minus the non-cash lines, and flagged as derived (A-54). Earning lines
  come from both lists, and their kind comes from `payClass` (or the client pay-code table for "other"
  lines). `earnAmount` and `otherEarnAmount` are kept in `provider_extensions`, not used.
### A-33 Time-dependent fields use an explicit `as_of` date
- **Decision:** values like "is this deposit active?" (UKG `active` plus dates) are evaluated
  against `as_of`. That date defaults to the fetch date for live data (`session.json` `saved_at`) and
  is fixed for fixtures (`session.json` `as_of`). Every evaluation leaves an `EVALUATED_AT_AS_OF`
  diagnostic, and a missing date gives `AS_OF_UNKNOWN` instead of a guess.
- **Why:** the output must be reproducible, so tests can't depend on today's date.

## Scope decisions from the model review (2026-10-13)

### A-34 Tax withholding setup is kept, not mapped
- **Issue:** each provider exposes federal and state withholding settings (filing status, allowances,
  extra withholding) in a different shape. Mapping them is a sizable extra model.
- **Decision:** v1 keeps them verbatim in `provider_extensions` and adds no canonical tax-setup fields.
- **Why:** nothing is lost, and the time goes to the four required data types first.

### A-35 Customer-configured labels stay unmapped
- **Issue:** some values are names a customer chose, for example UKG employee type "FT Exempt" or the
  isolved category code "FT". No provider documents what they mean.
- **Decision:** they map to `UNMAPPED`, keeping the label and raw value. There is no per-tenant mapping file.
- **Why:** reading "full-time" out of a customer's naming is a guess, not evidence (model principle 3).

### A-36 Output: JSON and SQLite
- **Decision:**
  - Every run writes `<record type>.json` (records sorted by ID), `summary.json` and
    `canonical.sqlite` (`src/normalization/export.py`).
  - In SQLite the records are linked by canonical ID: company, then employee, then deposits,
    deductions and paychecks. Paycheck lines, reconciliation checks and diagnostics have their own
    tables, and a `pay_statement_overview` view joins paychecks to employees and checks.
  - Every row also keeps the full canonical record as JSON in `record`, so nothing is lost.
  - Money stays exact TEXT, as in the JSON, because SQLite's REAL would round it.
  - Foreign keys are declared but not enforced. A paycheck may name an employee whose record wasn't
    fetched (`EMPLOYEE_NOT_IN_BUNDLE`), and `PRAGMA foreign_key_check` lists exactly those.
  - The canonical model is also exported as JSON Schema, one file per record type under `schemas/`.
    Tests check that every golden record validates against it.
- **Why:** JSON is easy to read and diff, and SQLite lets anyone query the linked records with plain SQL.

## Corrections and additions from the design audit (2026-10-13)

An independent design audit raised 15 findings. Each was checked against the specs; all held. The
entries above were updated where they were wrong (A-04, A-12, A-23, A-25, A-26, A-27, A-29), and the
entries below are new.

### A-37 HSA deposits are a different kind of deposit
- **Evidence:** in Prism `#/components/schemas/EmployeeDirectDeposit-HsaDepositSettings`, `method` PN
  means "Percent of Net after Taxes", while in ordinary `AchVoucher` it means "percentage of net
  after fixed". HSA account types HE/HES/HC/HCS also encode who funds the deposit (employee or
  company) and the destination (checking or savings).
- **Decision:** deposits carry `purpose` (`NET_PAY` or `HSA`) and, for HSA, `funding`. Methods are
  mapped per full source field, so the two `PN` values get different canonical methods.

### A-38 Prism earning quantity is hours *or* units
- **Evidence:** `#/components/schemas/Earning/properties/hoursUnits` is "hours or units paid", and
  `hoursWorked` is a separate field. The pay code's `payReason`
  (`#/components/schemas/ClientCodes-PayCode/properties/payReason`) is documented as "hours (H) or
  units (U)".
- **Decision:** each earning line has `quantity` with a unit (`HOURS`/`UNITS`/`UNKNOWN`), taken from
  the pay code's `payReason` via the client code table, plus a separate `hours_worked`. If the pay
  code isn't in the table, the unit is `UNKNOWN`.

### A-39 Contractor status is not a pay type
- **Evidence:** Prism `#/components/schemas/Client/properties/employee1099` is independent of
  `#/components/schemas/Compensation/properties/payMethod`. isolved puts "1099" inside `payType`.
- **Decision:** employees get a separate `worker_classification` (`EMPLOYEE`/`CONTRACTOR_1099`).
  isolved "1099" sets it, and leaves `pay_type` as `UNMAPPED`.

### A-40 Record links and paycheck-to-run joins
- **Evidence:** isolved checks carry `payrollRunNumber`, while run history has both `id` and
  `runNumber` (`#/definitions/AOS.PayrollOffice.RestAPI.Models.PayrollRunHistoryModel`). Prism batch
  lists carry periods per pay group (`#/components/schemas/BatchByDateResponse-BatchList-PayGroup`).
- **Decision:** every record carries explicit relationship keys (model §2.1). An isolved check
  joins its run on legal company + pay date + run number, and never by treating the run number as
  a run ID. An ambiguous or missing match leaves `payroll_run_id` null, with a diagnostic. Payroll
  runs keep periods per pay group.

### A-41 Deduction calculations keep their basis
- **Evidence:** Prism `#/components/schemas/DeductionCodeDetail/properties/calculationMethod`
  documents 29 methods. They distinguish gross pay from gross earnings, hours worked from hours
  paid, and percent from per-ten-thousand, and some round to the dollar.
- **Decision:** a calculation is {method, basis, value, rounding}, mapped code by code (model §7).
  Providers that give no basis (isolved, UKG) get `UNSPECIFIED`.

### A-42 Prism "other earnings" lines belong in the paycheck
- **Evidence:** `PayrollVoucher` has `earning[]` and `otherEarningsDetail[]`. `totalEarnings` equals
  `earnAmount + otherEarnAmount` on 333 of 420 live vouchers (A-32).
- **Decision:** both lists become earning lines, otherwise gross can't reconcile.

### A-43 Fixtures with live key aliases are validated on their contents
- **Evidence:** `#/components/schemas/PayrollResponseWithPagination` documents `payrollVouchers`
  and permits additional properties. A fixture using the live alias `payrollVoucher` would therefore
  pass validation with *any* contents.
- **Decision:** before schema validation, the fixture checker translates known live aliases back to
  their documented names (`payrollVoucher` → `payrollVouchers`, `clientPayrollSchedule` →
  `clientPayrollSchedules`), so the contents are validated against the real schema. Converters still
  receive the alias form, as live data has it.

## Found while running the PrismHR converter on live data (2026-10-13)

### A-44 PrismHR gender codes
- **Evidence:** `#/components/schemas/Person/properties/gender` lists "M, F, X or D" with no meanings.
- **Decision:** M maps to `MALE` and F to `FEMALE`. X and D stay `UNMAPPED` with the raw value kept,
  because their meanings aren't stated.

### A-45 PrismHR citizenship arrives as the documented description, not the code
- **Evidence:** `#/components/schemas/Compensation/properties/citizenshipStatus` documents codes Z01–Z04
  with their meanings. All 18 live values are the description text itself, e.g. "A citizen of the
  United States".
- **Decision:** both the codes and their exact documented descriptions map to the canonical values.
  Anything else stays `UNMAPPED`.

### A-46 PrismHR placeholder dates
- **Evidence:** live `compensation.effectiveDate` and pay-rate history contain `0000-01-01`, which is
  not a valid date. Pay-rate history also contains `9999-12-31`. Neither is documented.
- **Decision:** `0000-01-01` becomes null with an `INVALID_DATE` warning. `9999-12-31` is kept as a
  date with an info diagnostic, consistent with A-25. Nothing is guessed.

### A-47 Live PrismHR responses don't match their own schema, in three specific ways
- **Evidence:** of 428 live 200 responses, 422 validate against the spec once `null` is allowed in
  typed fields. The remaining six deviations are:
  - `extension` is `null` where an object is declared;
  - every employee lacks the "required" `client.hawaiiMedWaivers`;
  - `clientMaster.regRebuild[].regRebuildDate` arrives as epoch milliseconds (e.g. `1550080171000`)
    where a string is declared.
- **Decision:**
  - Converters accept null or missing for every field. `regRebuildDate` is not mapped, so it stays
    raw in extensions.
  - The fixture generator fills every required property the scenario doesn't set with `null`, as
    live data does. Fixture validation allows `null` and nothing else (`fixtures/validate.py`).
- **Why:** the fixtures should look like what PrismHR actually sends, while staying checkable
  against the published contract.

## Found while building the isolved converter (2026-10-13)

### A-48 isolved employment status: only implied system statuses are mapped
- **Evidence:**
  - `#/definitions/AOS.PayrollOffice.RestAPI.Models.EmployeeModel/properties/employmentStatus` is
    "The current employment status description", with no list of values. The client endpoint
    (`/api/clients/{c}`) returns only its code, name, ID and links, so there is no client status
    table to look the text up in.
  - `/employees/{e}/statuses` (`EmployeeEmploymentStatusModel`) marks each history row with
    `isImpliedStatus`. All 31 live rows are implied, with negative IDs that belong to no client table:
    "Active" (`statusId` −1, 30 rows) and "Terminated" (−2, 1 row). These are also the only two live
    `employmentStatus` values (29 Active, 1 Terminated).
- **Decision:** "Active" maps to `ACTIVE` and "Terminated" to `TERMINATED`, but only when the
  employee's own status history shows that description as an implied status. Any other description,
  such as a customer status like "Leave - FMLA", stays `UNMAPPED` with its label and a
  `CUSTOMER_STATUS` info diagnostic.
- **Why:** implied statuses are isolved's own, so their meaning is fixed. Customer statuses are
  configurable labels (A-35); "on leave" can't be read from a name.

### A-49 isolved deduction categories come from the client pay item's system classification
- **Evidence:**
  - Employee pay items (`EmployeePayItemModel`) have a name, code and type ("Deduction", "Earning",
    "Memo Calc") but no category. Client pay items (`ClientPayItemModel`) add `systemBenefitType` and
    `systemPayItemType`: the system item the client's item is built on. The spec describes them only
    as "System Benefit Type" and "System Pay Item Type".
  - Live, all 1230 employee pay items (150 earnings, 570 deductions, 510 memo calculations) link to a
    client pay item by title (`payItemName` = `title`). Titles are unique per client (56 of 56) but
    codes are not (41 distinct codes across 56 items), so linking by code would pick a different item
    for 360 of the 1230. `payItemId` is documented as deprecated and matches no client item ID.
  - Check lines link the same way. On all 154 live earning and deduction lines, `itemDescription` is
    a client item's title and `itemCode` is that item's code. Garnishment lines (4) don't link.
  - `/employees/{e}/garnishments` returns 404 for the 29 of 30 live employees without a garnishment.
- **Decision:**
  - Category and tax treatment come from a table keyed by (`systemBenefitType`,
    `systemPayItemType`) in `providers/isolved/codes.py`. For example, ("401(k)", "401K Loan") is a
    `RETIREMENT_LOAN`, and ("Dental Pre-Tax 125", any type) is a pre-tax `SECTION_125` deduction.
  - A system pay item type that says "post-tax" or "after-tax" sets the treatment to post-tax.
  - Unknown pairs stay `UNMAPPED`, with the pair kept as the raw value.
  - Only "Deduction" items become elections. Earning and memo items stay in the employee's
    `provider_extensions`.
  - Garnishments are always `GARNISHMENT`. A 404 from the garnishments endpoint means "none", not an
    error.
- **Why:** the system types are isolved's own classification. Titles are customer-chosen text (A-35).

### A-50 isolved SSN last 4 comes from check records
- **Evidence:** `EmployeeModel.ssn` is required ("Employee SSN or identification type value") but is
  null on all 30 live employees. `CheckModel.employeeSSN` ("Employee Social Security Number") arrives
  masked as `XXX-XX-` plus the last four digits, on all 430 listed checks and all 15 check details.
- **Decision:** when the employee record has no SSN, `national_id.last4` comes from the employee's
  checks, with `source_field` `checks[].employeeSSN` and `masked_at_source` true. Employees with no
  checks have no national ID.
- **Why:** the last four digits are all any record keeps (A-23), and checks are the only place isolved
  returns them.

### A-51 isolved check list vs check detail, and year-to-date-only lines
- **Evidence:**
  - The legal-level check list (`/legals/{l}/checks`, 430 live rows) is a summary. Its line-item
    arrays are empty on all 430 rows, and `checkTypeDescription` is null on all 430.
  - For the 15 checks also fetched in detail (`/employees/{e}/checks/{id}`), `checkSequence` is 1 in
    the list and 0 in the detail on all 15. `employeeName` differs on one check, and address fields
    on a few others.
  - Detail arrays also hold lines with no `check*` value at all: 52 of 121 earning lines and 26 of
    137 tax lines live. They carry only month-, quarter- or year-to-date amounts from earlier checks.
- **Decision:**
  - The detail is used whenever it was fetched.
  - A list-only check becomes a pay statement with its header and totals, and no lines. Its type is
    `UNMAPPED` (missing, so no warning), it gets a `DETAIL_NOT_FETCHED` info diagnostic, and the
    line-based checks are skipped.
  - The list has no deposit lines (`directDeposits` is null on all 430 rows), so its
    `directDepositAmount` becomes one direct-deposit payment without an account. `payments = net`
    can then still be checked.
  - Checks link to employees by `employeeId` only, never by name.
  - Only lines with a `check*` value are this paycheck's lines. The others stay in
    `provider_extensions`.
- **Why:** the list omits fields rather than contradicting them. The name and address are snapshots,
  kept raw in `provider_extensions`.

### A-52 Live isolved employee records don't match their own schema, in two ways
- **Evidence:**
  - `EmployeeModel.maritalStatus` is "Marital status code" with `maxLength` 1, but live sends the
    description: "Single" (9), "Married" (10) or null (11). `/api/lookup/maritalStatuses` maps each
    code to its description. `gender` and `citizenship` are documented as descriptions and arrive as
    descriptions.
  - `idType` is required but absent from all 30 employee records and from every employee-list row.
  - Of 210 live 200 responses, 177 validate against the spec once `null` is allowed. The other 33
    (30 employee details and 3 employee-list pages) all lack `idType`, and 22 of them also send a
    marital status longer than one character.
- **Decision:**
  - Marital status, gender and citizenship map by their lookup description. A code (the documented
    form) is first translated through the lookup, and `raw` keeps exactly what was sent.
  - The fixtures send both forms.
  - Fixture validation ignores exactly one deviation, `maxLength` on `maritalStatus` (`DEVIATIONS` in
    `fixtures/validate.py`). The generator fills `idType` with null, like other unset required fields
    (A-47).
- **Why:** as in A-47, fixtures should look like live data while staying checkable against the
  published contract.

### A-53 isolved earning kinds come from the system earning each pay item is built on
- **Evidence:**
  - A check's earning line has only `isMemoEarning` to say what kind of pay it is. Its client pay item
    (linked by title, A-49) names the system earning it is built on (`systemPayItemType`), and
    `/api/system/earnings` describes each system earning in isolved's own words:
    - "Regular": "Earnings paid based on the employee hourly rate or per pay Salary";
    - "Vacation", "Sick" and "Holiday": "Earnings paid based on hours input times the employee
      normal hourly rate";
    - "Bonus": "Earnings paid based on hours or dollar input"; "Commission": "Earnings paid based
      on dollar input only";
    - "Overtime @ Flat 1.5": "Overtime paid at 1.5 ee hourly rate"; "Overtime - Blended Rate":
      "Blended rate used to pay OT hours";
    - "Other Hrs or Dollars": "… Fully taxable. Paid.";
    - "Misc Non Taxable": "Non-taxable earning. Paid to ee. … reimbursement earning.";
    - Group Term Life items: "Group Term Life - taxable amount over $50K" (and, for one variant,
      "Not Paid").
  - "ShiftDiff" is described only as "Shift Diff", but live it sits inside `grossPay` on both checks
    where it appears, so it is paid.
- **Decision:**
  - Memo lines are `MEMO`, from the flag.
  - Otherwise, system benefit type "Group Term Life" is `NON_CASH_FRINGE`, "Misc Non Taxable" is
    `REIMBURSEMENT`, and the paid earnings above are `EARNINGS` (`EARNING_CLASS` in
    `providers/isolved/codes.py`).
  - Any other system earning, for example "1099M Non EE Comp", stays `UNMAPPED` with an
    `UNMAPPED_CODE` warning. Its description doesn't say whether it is paid.
  - The kind keeps the system benefit type and pay item type as its raw value.
- **Why:** these are isolved's own definitions, not the customer's titles. Live, all 42 non-memo
  earning lines on the 15 detailed checks get a kind this way.

### A-54 Gross pay and gross wages mean the same thing for every provider
- **Issue:** the providers' headline gross figures differ. Prism's `totalEarnings` includes non-cash
  pay (A-32). isolved reports both `grossWages`, which includes group-term life, and `grossPay`,
  which doesn't (A-28). Mapping each provider's headline figure to one field would make that field
  mean different things.
- **Decision:**
  - `gross_wages` is every earning counted in gross, non-cash ones included: Prism `totalEarnings`,
    isolved `grossWages`.
  - `gross_pay` is the part actually paid: gross wages minus non-cash earnings (`NON_CASH_FRINGE`,
    `REPORTED_TIPS`, and `MEMO` lines counted in gross). isolved `grossPay` is exactly that. For Prism
    it is derived, flagged `derived` with its formula, and only when every counted line has a known
    kind. Otherwise it is left null with a `GROSS_PAY_NOT_DERIVED` info diagnostic.
  - Each earning line's `in_gross` says whether the provider counts it in gross wages.
  - Checks (reported, never adjusted):
    - gross wages = sum of the lines counted in gross;
    - gross wages − non-cash earnings = gross pay, when both are provided;
    - gross pay − employee taxes − deductions = net;
    - payments = net.
- **Live result:** Prism 1175 of 1175 checks pass, with gross pay derived on every voucher that has
  lines. isolved 468 of 468 pass, including the new gross check on all 15 detailed checks.

## Found while building the UKG Ready converter (2026-10-13)

### A-55 UKG employee status
- **Evidence:** `#/schemas/106` documents `status` only as "This field is only used for GET". Live,
  "Terminated" appears exactly when `dates.terminated` is set (12 of 12), and "Active" exactly when it
  isn't (3 of 3).
- **Decision:** "Active" and "Terminated" map to `ACTIVE` and `TERMINATED`. Anything else stays
  `UNMAPPED` with its text.

### A-56 UKG pay: amounts, hours and pay periods
- **Evidence:**
  - `#/schemas/122` gives each compensation record an `amount` per `amount_period`, an `hourly_pay`,
    a `time` per `time_period` ("Time is represented in milliseconds") and `num_pp_in_year`.
  - Live, all 27 records with an amount agree: `amount` ÷ hours per period = `hourly_pay`. For example,
    a YEAR amount ÷ 2080 hours (7,488,000,000 ms) gives the hourly pay, and a PAY_PERIOD amount × 26
    periods ÷ 2080 hours gives it too.
  - Every employee also has a placeholder record dated 1900-12-31, with no amount and
    `num_pp_in_year` 0.
  - `lookup/pay-types` is documented with the sample names "Pay Type 1" and "Pay Type 2", so pay types
    are customer-defined. Live they are "Hourly" and "Salaried". Employee types ("FT Exempt",
    "Consultant") are customer-defined too.
- **Decision:**
  - The current pay is the latest record in effect at `as_of` (A-33). Every record is kept in `history`,
    including records dated after `as_of`.
  - Rates keep their period, and `hourly_pay` is added as a rate per hour. `time` becomes standard hours
    (derived, with the raw milliseconds kept) per `time_period`.
  - `num_pp_in_year` sets the pay frequency: 52 is weekly, 26 biweekly, 24 semimonthly, 12 monthly,
    because each count is that frequency's definition. Any other count is `OTHER` with the count, and 0
    means not set.
  - Pay type and employee type stay `UNMAPPED` with their names (A-35). `WEEK` and `MONTH` amounts
    weren't seen live.

### A-57 UKG payroll and pay statement types and statuses
- **Evidence:**
  - `lookup/payroll-types` is documented as "the list of supported payroll types". The documented sample
    and the live tenant list the same names (Regular, Void, Correction, Historical and others) under
    different IDs.
  - `lookup/pay-statement-types` is documented the same way, but the live tenant also has names like
    "Comm" and "Regular 2", which a customer must have added.
  - Payroll `status` (`#/schemas/360`) lists values without definitions. The documented actions run
    OPEN → close → CLOSED → finalize ("Performs the finalize process on the specified payrolls if
    closed") → FINALIZED.
  - All 89 live payrolls and 28 statements are `OPEN` (A-13).
- **Decision:**
  - Payroll types map by name, never by ID: Regular, Void, Correction and Historical.
  - Pay statement types map only for the documented sample names Regular, Manual and Historical.
  - Payroll statuses: OPEN, CLOSED and SUBMITTED map to themselves, FINALIZED to `COMPLETED`, and the
    `*_FAILED` values to `FAILED`. NEW stays `UNMAPPED`.
  - Anything not finalized gets a `NOT_FINALIZED` diagnostic.

### A-58 UKG pay statement line types, and "Fringe" payments
- **Evidence:**
  - UKG pay statements give no gross or net. Each line has a `type_name` in the form
    "<kind> (<modifiers>)". Live earnings show "Earning", "Earning (Auto)", "Earning (Auto Reduce)",
    "Earning (Fringe, Auto)" (code "GTL-Imp Inc") and "Reimbursement(Neg Ded, Auto)". The docs sample
    shows "Deduction (Manual)".
  - Payments are "Check", "Direct Deposit" and "Fringe".
  - On every live statement (22 of 22 in the first fetch, 61 of 61 in the second), each "Fringe"
    payment equals the fringe earnings, and
    `sum of earnings − fringe earnings − employee taxes − deductions = check + direct deposit`.
- **Decision:**
  - "Earning" lines are `EARNINGS`, "Reimbursement" lines `REIMBURSEMENT`, and lines with the
    "Fringe" modifier `NON_CASH_FRINGE`.
  - A modifier outside those seen (Auto, Auto Reduce, Manual, Fringe, Neg Ded) leaves the line
    `UNMAPPED` with a warning, since it could change the meaning.
  - "Fringe" payment rows aren't payments: nothing is paid. They stay in `provider_extensions`.
  - Gross wages are derived as the sum of the lines. Gross pay is derived by subtracting the fringe
    lines (A-54). Net pay is derived from the check and direct deposit payments. The
    `gross pay − taxes − deductions = net` check passes on every live statement where net can be derived:
    22 of 22, and 60 of 61 in the second fetch, where one statement has an earning but no payments.
  - Lines with no amount (3 earnings and 3 check payments live) carry no money for the statement, so
    they don't become lines. They stay in `provider_extensions`.
  - Each tax line becomes one employee line and one employer line, each with its own subject wages.
    Deduction `er_amount` becomes an employer contribution.

### A-59 One amount arrived as a binary floating-point number
- **Evidence:**
  - One live UKG tax amount is `2.4699999999999998`. That is 2.47 after a binary floating-point
    computation.
  - The pay statement page types `ee_amount` as a float, and says "Amount should be rounded to a
    Penny".
  - Such values are rare: 1 of 988 UKG decimals in the first fetch and 3 of 2,555 in the second, against
    0 of 31,602 Prism and 0 of 8,387 isolved decimals.
- **Decision:** keep it exactly as sent ("never rounded"), with a `FLOAT_ARTIFACT` info diagnostic
  that names the penny amount. Derived sums carry it too. The checks' 0.01 tolerance absorbs it.
- **Why:** rounding would be a guess about the provider's intent. Reporting it lets a consumer decide.

### A-60 UKG EINs: the lookup doesn't list them all
- **Evidence:** `lookup/eins` returns one EIN. The 89 live payrolls name two: the listed one (46
  payrolls) and a second one (43), each with its name and tax ID. All 15 sampled employees name the
  first.
- **Decision:**
  - The company's `employers[]` holds every EIN from the lookup, plus any EIN only payrolls name, with an
    `EIN_FROM_PAYROLL` info diagnostic.
  - Employees and payroll runs carry the EIN as `legal_entity_id`.
  - With several EINs there is no single `own_tax_id`, so it stays null.

### A-61 Live UKG responses don't match their own schema, in five specific ways
- **Evidence:** of 112 live 200 responses, 78 validate once `null` is allowed. The rest show:
  - an unexpected `ein_name` on every employee (15 of 15);
  - an unexpected `_links.country-fields` on employees, in both the list and the detail;
  - pay-info `eeo4_classification` and `eeo4_function` of "UNKNOWN", which isn't in the enum (15 of 15);
  - `num_pp_in_year` 0, below the documented minimum of 1, on the placeholder records (A-56);
  - `pay_grade.parent.code` "S10", where an integer is declared (3).
- **Decision:**
  - Converters accept all of these.
  - The fixtures reproduce two of them, `ein_name` and the placeholder's 0. Validation ignores exactly
    those two (`DEVIATIONS` in `fixtures/validate.py`), and reports any other additional property.
  - Each UKG schema block is validated as its own document, with its own `$schema` version, because its
    `$ref`s point at its own definitions.

## Field coverage (2026-10-13)

### A-62 Every source field is mapped, kept or dropped for a stated reason
- **Method:** `python -m normalization coverage` runs the converters with tracing on and walks every
  saved response leaf by leaf ([docs/FIELD_COVERAGE.md](docs/FIELD_COVERAGE.md), generated from the
  live fetches). Each field is labeled:
  - mapped into a canonical record;
  - kept in `provider_extensions`;
  - dropped, with a reason;
  - a reference table read by code;
  - or unused.
  
  The tracing also catches any field that is both mapped and kept, which means it was read after the
  leftovers were taken.
- **What it found, and the fixes:**
  - Some responses reached no record at all. These are now kept with the record they describe:
    - PrismHR active benefit plans, on the employee (there is no benefit plan record, model §7);
    - isolved status history and alternate pay rates, on the employee;
    - the isolved client record, on the company;
    - the fields a PrismHR voluntary deduction adds to the matching election.
  - Some mapped fields were also copied into `provider_extensions`:
    - PrismHR deposit bank name, routing number and status;
    - PrismHR run pay date, status and description;
    - earlier, isolved and UKG employee names and dates.

    Leftovers are now always taken after the record is built, and a test keeps that count at zero.
  - isolved's documented `terminationDate`, `terminationReason` and `workLocation` (with
    `workLocationDashDescription`, "'location id' - 'location description'") are now mapped. They had
    only been kept.
- **What stays unread:**
  - crawl indexes (employee lists), since each record is read from its own response;
  - list rows whose detail response was used instead;
  - lookups the converters don't need, because lines carry their own codes and names;
  - request echoes and paging envelopes.
- **Why:** "preserve what the source data means" includes not losing it. The report makes every
  field's fate checkable.
