# Assumptions, decisions and limitations

Each entry has four parts: **issue**, **evidence**, **decision** and **why**.

- **Spec evidence** is a JSON pointer into the files under `contracts/`. These abbreviations are used:
  - **Prism** = `contracts/prismhr/openapi/prismhr-2025.09.openapi.json`
  - **isolved** = `contracts/isolved/openapi/isolved-v6.swagger.json` (the primary snapshot only)
  - **UKG** = `contracts/ukg-ready/reference-schemas.json`, plus HTML pages under `contracts/ukg-ready/reference-docs/`
- **Live evidence** comes from read-only requests to the demo tenants on **2026-10-12**. The raw
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

### A-02 Replacing the starter scaffold (planned)
- **Issue:** the optional starter does three things that get in the way:
  - it refuses isolved and UKG through a distribution "readiness" gate;
  - `ENTITIES` has no deposits or deductions;
  - `tests/test_starter.py` asserts that the adapters stay unimplemented.
- **Decision:** replace the CLI and the adapters, and replace `test_starter.py` with real tests.
  `contracts/` and `test_reference_integrity.py` stay untouched.
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
  - only the demo company IDs that `/signin` returned;
  - redirects are re-checked on every hop.

  Tokens stay in memory, are never written to disk, and appear in no log. Offline tests cover each rule.
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
- **isolved:** client 4046, both legal companies (5797 and 5806), 30 employees, 15 checks and 8
  payroll runs.
- **UKG Ready:** company 33704016, 15 employees, 10 payroll runs and 22 pay statements.
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
- **Decision:** deduction setup comes from `/employees/{e}/payItems` (589 deduction items live), and
  payroll deductions come from check details.
- **Why:** the alternative endpoints are documented and readable, so nothing is lost.

### A-11 isolved has only historical, imported payroll
- **Evidence:**
  - Pay group 7612 has 231 runs. 36 are "Completed Payroll Run" (all "Data Conversion", 2018) and
    195 are "Payroll Not Processed".
  - The other pay groups return 404 (no history).
  - All 15 checks found are type "Adjustment" from conversion runs.
- **Decision:** normalize these as they are, with run type `HISTORICAL_IMPORT`. Synthetic fixtures
  cover regular runs.

### A-12 UKG has no deduction setup endpoint on this tenant
- **Evidence:** `/employees/{aid}/deductions` (UKG `#/schemas/132`) returns 404 "Unresolvable URL"
  for all 15 employees.
- **Decision:** there are no UKG `DeductionElection` records. UKG deductions appear only as
  pay-statement lines. This is a documented gap.

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

### A-23 Masking differs by provider
- **Evidence:**
  - Prism SSNs come back fully masked (`***-**-****`). Birth dates come back **unmasked**, although
    `#/paths/~1employee~1v1~1getEmployee/get/description` says they are masked by default.
  - isolved returns full direct-deposit account numbers, and no SSN from this endpoint.
  - UKG returns full SSNs.
- **Decision:** our output keeps only the last 4 digits of SSNs and account numbers, whatever was
  received, and records whether the provider had already masked them. Birth dates are kept as
  employee data.

### A-24 UKG pay-statement hours are milliseconds
- **Evidence:** UKG `#/schemas/364` types earnings `hours` as an integer with no unit. Live, **all 23**
  earning lines that have both hours and a rate satisfy `(hours ÷ 3,600,000) × base_rate = ee_amount`,
  and none satisfies `hours × base_rate`. Milliseconds are also documented elsewhere in the same API
  (compensation `time`, pay-info `standard_work_day`).
- **Decision:** convert to hours, keep the raw value, and record the formula.

### A-25 UKG uses 2099-12-31 as an end date
- **Evidence:** all live deposits have `active_to` = 2099-12-31. The documented open-ended sentinels
  are 9999-12-31 and 1900-12-31.
- **Decision:** keep 2099-12-31 as a real date, with an info diagnostic. Only documented sentinels
  become null.

### A-26 UKG direct-deposit percent methods have no documented meaning
- **Evidence:** UKG `#/schemas/137` lists the `calc_method.type` enum values with no descriptions.
  Live, only `FULL` appeared, with `display_name` "Entire/Remainder".
- **Decision:** map GROSS_EARNING, NET_PAY and DIRECT_DEPOSIT_PER_OF_REMAINDER by their enum names,
  but check `display_name` whenever it is present and add a diagnostic if they disagree.
- **Why:** these are the provider's own enum values, not customer labels, but they are unverified.

### A-27 isolved `payFrequency` is a Frequencies lookup ID
- **Evidence:** the spec types it only as an integer
  (`#/definitions/AOS.PayrollOffice.RestAPI.Models.PayGroupModel/properties/payFrequency`). Live
  `/api/lookup/Frequencies` maps 12 = Monthly, 24 = Semi-Monthly, 26 = Bi-Weekly and 52 = Weekly. The
  pay groups match their names: "Biweekly" is 26 and "Monthly" is 12.
- **Decision:** resolve it through the lookup. The lookup's description becomes the label, and the ID
  gives `periods_per_year`.

### A-28 isolved check buckets and its two gross figures
- **Evidence:** for each check, the spec gives `check*`, `current*`, `ptd`, `mtd`, `qtd`, `ytd` and
  `ftd` amounts without explaining them. On all 15 live checks:
  - `checkDollars` equals `currentDollars` on every line;
  - `grossWages` equals the sum of non-memo earnings;
  - `grossPay` − employee taxes − deductions − garnishments = `netPay`;
  - `checkAmount + directDepositAmount = netPay`.

  `grossPay` is a little below `grossWages` on all 15 (by $0.37 to $9.92), and nothing documents why.
- **Decision:** `check*` is "this paycheck". `gross_pay = grossPay`, because it reconciles to net,
  and `gross_wages = grossWages` is kept as a separate figure. The difference is a documented open question.

## Unresolved, and how we handle it

### A-29 Percent scale (5 vs 0.05)
- **Evidence:**
  - No live direct deposit uses a percentage: Prism is all method B, isolved uses fixed or net
    accounts, and UKG is all `FULL`.
  - isolved "Percent" parameters are all 0.0.
  - Prism deductions with `usePercent = true` have amounts 3.0 and 12.0. A fraction scale would mean
    300% and 1200% of pay, which is impossible.
- **Decision:**
  - Prism deduction percents are percentage points.
  - Percentages without evidence are treated as points too, but get a `PERCENT_SCALE_UNVERIFIED`
    diagnostic.
  - Synthetic fixtures exercise percent allocations.

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

### A-32 PrismHR `totalEarnings` doesn't always equal earnings + other earnings
- **Evidence:** `totalEarnings = earnAmount + otherEarnAmount` on 333 of 420 vouchers. The other 87
  differ by small amounts, often multiples of $0.92. gross − employee taxes − deductions = net holds
  on 334 of 420.
- **Decision (for now):** use `totalEarnings` as the provided gross, and report the mismatch as a
  diagnostic. Investigation continues; the likely sources are benefit or imputed amounts.

### A-33 Time-dependent fields use an explicit `as_of` date
- **Decision:** values like "is this deposit active?" (UKG `active` plus dates) are evaluated
  against `as_of`. That date defaults to the fetch date for live data and is fixed for fixtures.
- **Why:** the output must be reproducible, so tests can't depend on today's date.
