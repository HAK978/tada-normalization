# Decision log

Every judgment call in this project, recorded as issue, evidence, decision and why.
[ASSUMPTIONS.md](../ASSUMPTIONS.md) summarizes them, with the design, the known limitations and where
each of the organizer's instructions is met. Entries are grouped by topic. Their IDs (A-01 to A-91) are
stable references used in the code, the tests and the other docs, so they don't run in order.

**Evidence** comes from two places:

- **The specs**, cited as JSON pointers into `contracts/`:
  - **Prism** = `contracts/prismhr/openapi/prismhr-2025.09.openapi.json`
  - **isolved** = `contracts/isolved/openapi/isolved-v6.swagger.json` (the primary snapshot only)
  - **UKG** = `contracts/ukg-ready/reference-schemas.json`, plus the pages under `contracts/ukg-ready/reference-docs/`
- **Live data**, from read-only requests to the three demo tenants (A-07). Raw responses never leave the
  machine that fetched them, so this file quotes counts and code values only.

| Topic | Entries |
|---|---|
| [How the data was obtained, safely](#how-the-data-was-obtained-safely) | A-01 to A-07, A-74, A-85 |
| [Rules that apply everywhere](#rules-that-apply-everywhere) | A-64, A-70, A-73, A-35, A-23, A-25, A-29, A-31, A-33, A-59 |
| [Company](#company) | A-30, A-09, A-15, A-60, A-84 |
| [Employee](#employee) | A-48, A-89, A-55, A-44, A-45, A-39, A-50, A-20, A-19, A-27, A-56, A-46, A-34, A-75, A-76, A-77, A-79, A-80, A-81, A-82 |
| [Direct deposits](#direct-deposits) | A-37, A-26, A-14 |
| [Deductions](#deductions) | A-41, A-49, A-12, A-08, A-83, A-10, A-17, A-87, A-91, A-88 |
| [Payroll runs and paychecks](#payroll-runs-and-paychecks) | A-54, A-32, A-28, A-58, A-51, A-42, A-18, A-38, A-24, A-53, A-67, A-68, A-40, A-21, A-57, A-13, A-11 |
| [Where live data differs from the specs](#where-live-data-differs-from-the-specs) | A-90, A-16, A-78, A-22, A-47, A-52, A-61 |
| [Unknown values: review and mapping files](#unknown-values-review-and-mapping-files) | A-65, A-69, A-66, A-86 |
| [Output, provenance and tests](#output-provenance-and-tests) | A-36, A-71, A-62, A-72, A-43 |
| [Optional extension: writing an employee](#optional-extension-writing-an-employee) | A-63 |

## How the data was obtained, safely

### A-01 Our own repository, with no link to the organizer's
- **Decision:** a new git history whose first commit is the organizer's starter files, unchanged. There
  is no fork, no upstream remote and no shared history.
- **Why:** the submission is clearly separate, and nothing can be pushed to the organizer's repository by
  mistake. `tests/test_reference_integrity.py` still passes, which proves `contracts/` is byte-identical.

### A-02 The starter scaffold was replaced
- **Issue:** the optional starter refused isolved and UKG through a distribution "readiness" gate, had
  no deposits or deductions in its entity list, and its test asserted that the adapters stay
  unimplemented.
- **Decision:**
  - `src/normalization/__main__.py` is the project's CLI, and the stub adapters became the converters
    under `providers/`. The starter's test gave way to the real tests.
  - `references.py` stays, because `test_reference_integrity.py` imports it. Its one changed line
    imports the provider list from `providers/`.
  - `contracts/` and `test_reference_integrity.py` are untouched. The organizer's README, the brief, is
    kept unchanged as `ASSIGNMENT.md`, where its relative links still work.
- **Why:** the gate checked distribution metadata, not data correctness, and the organizer approved
  sharing the reference pack with candidates ([ASSIGNMENT.md](../ASSIGNMENT.md), "Reference status").

### A-03 Stack
- **Decision:** Python 3.11+, with Pydantic v2 for the canonical model (exported as JSON Schema),
  `jsonschema` to validate fixtures against the provider schemas, and httpx for live calls. pytest,
  Hypothesis, ruff and mypy are the development tools.
- **Why:** typed models with a schema export make the canonical format checkable by anyone, in any
  language.

### A-04 Live access is read-only and scope-guarded
- **Issue:** the demo tokens can write, and the PrismHR and isolved tokens also reach companies beyond
  the demo ones (sign-in service README).
- **Decision:** every live request passes `src/normalization/live/scope.py` before it is sent: GET only,
  on the `/signin` base URL's host, to allowlisted endpoints, for the demo company IDs `/signin` returned.
  Also:
  - Redirects are never followed automatically. Our own redirect loop re-checks every hop, and a
    redirect from the sign-in service is refused, because following it would resend the API key.
  - Saved captures, the index and log lines are scrubbed of the API key, the session's tokens and
    embedded signed tokens. Headers that carry credentials are dropped.
  - Numbers are saved exactly as the provider wrote them (`normalization.exactjson`).
  - The check itself refuses any method but GET, so read-only doesn't rest on the client having no other
    method. It also refuses a query parameter that could name a company in a form it doesn't check: a
    second spelling of PrismHR's `clientId` (`ClientId`), or a company ID on isolved and UKG, whose paths
    carry the company.

  Offline tests reproduce each attack and fail if its guard is removed.
- **Why:** these are real provider test systems, so a mistake must be impossible, not merely unlikely.

### A-05 One exception: PrismHR employer lookups
- **Issue:** `system/v1/getEmployerDetails` is not keyed by client. Called without an `employerId`, it
  lists every employer in the tenant.
- **Decision:** allow it only for employer IDs that a demo client's own `getClientMaster` response
  references (`employerId`, `altEmployer[]`). A request without an `employerId` is always refused.
- **Outcome:** the 25 demo clients reference employers 1, 5, 10, 20, 125 and 138. All six lookups return
  403 (A-09).

### A-06 Live data is never committed; tests use synthetic data
- **Decision:** live responses go to `.discovery/`, which is gitignored. Tests and fixture generation run
  offline on seeded synthetic scenarios, validated against each provider's published schema.
  `fixtures/MANIFEST.json` records how each scenario was made, as the starter's stub asked ("your seed,
  schema validation and generation manifest"): the builder and its seed, the spec file and its SHA-256,
  the schema each response matches, the deviations validation allows (A-52, A-61), and a SHA-256 of
  every file written. `scripts/generate_fixtures.py --check` fails when it no longer matches.
- **Why:** the brief forbids committing downloaded records, and live responses contain full SSNs (UKG)
  and bank account numbers (isolved).

### A-07 What was fetched
- **The fetches the entries name,** all read-only and through the scope guard (A-04):
  - **First sample (2026-10-12).** Most entries were decided on it, and their counts come from it unless
    they say otherwise.
    - PrismHR: 4 of 25 clients (51 employees, 420 vouchers from 33 payroll batches, 2015–2026), plus the
      master records of all 25.
    - isolved: client 4046 and both its legal companies (5797 and 5806): 30 employees, 430 checks listed
      (15 also in detail) and 231 payroll runs (8 in detail).
    - UKG: company 33704016: 15 employees, 89 payrolls (10 in detail) and 28 pay statements (22 in
      detail).
  - **Second UKG fetch (2026-10-13),** taking each pay statement's owner first, as the isolved crawl does:
    61 pay statements.
  - **Full fetch (2026-10-13),** with the crawl's default limits. Entries from A-65 on count on it.
    - PrismHR: all 25 clients, 194 employees and 2,403 vouchers (2,022 responses);
    - isolved: 45 employees, 430 checks (40 in detail) and 231 runs (14 in detail) (391 responses);
    - UKG: 25 employees, 89 payrolls (23 in detail) and 63 pay statements, all in detail (244 responses).
  - **The probe (2026-10-14):** every candidate endpoint, asked for 35 PrismHR employees and every fetched
    isolved and UKG employee (A-74). Entries from A-74 on count on the fetch that followed it, with the
    added endpoints, or say they count on the probe.
  - **Final fetch:** PrismHR on 2026-10-16 (3,430 responses), isolved and UKG on 2026-10-15 (572 and 378
    responses). The README's live counts and [docs/FIELD_COVERAGE.md](FIELD_COVERAGE.md) come from it.
- **Stable across fetches.** Every fetch after the full one returned the same records as the one before,
  apart from what the endpoints and request options it added brought (A-48, A-74, A-87, A-91) and notes
  that name the evaluation date (A-33).
- **Sample size.** The crawl takes at most 25 employees per company (`--max-employees`); isolved and UKG
  take each paycheck's owner first. The tenants list 668 PrismHR, 138 isolved and 103 UKG employees, and
  194, 45 and 25 were fetched. So 926 of the 2,403 PrismHR paychecks, 6 of the 63 UKG paychecks and the 3
  PrismHR retirement loans (A-87) belong to employees whose records weren't fetched. Each such record
  says so (`EMPLOYEE_NOT_IN_BUNDLE`), and its canonical employee ID is the one that employee's record
  would have, so a larger fetch links it. "Every employee" elsewhere in this file means every fetched one.
- **Limitation:** codes that never appeared live are mapped from the documentation only.

### A-74 Every documented read endpoint is fetched or has a recorded reason
- **Issue:** checks that look only at fetched responses (field coverage, the missing-vs-zero sweep, the
  property tests) can't see an endpoint that was never fetched. isolved and UKG keep employee data in
  endpoints of their own (UKG demographics and contacts, isolved job and category history), as PrismHR
  does change history and dependents. Only comparing the fetch list with the specs finds them.
- **Method:**
  - The specs document 855 read (GET) endpoints: PrismHR 253, isolved 302 and UKG 300 (its documentation
    index; 260 of them have an extracted schema). Each was sorted by topic.
  - Each one in the five data types that wasn't fetched was compared, field by field, with what was.
  - Every candidate was asked live (the probe, A-07), read-only, for the demo companies only and through
    the scope guard (A-04): 35 PrismHR employees in 13 clients, and the 45 isolved and 25 UKG employees
    fetched.
  - A topic rule reads an endpoint's tag or path, and a tag can hide data: PrismHR files retirement loans,
    retirement plans, flex plans and benefit adjustments, all deduction setup, under "benefits" (A-87,
    A-91). So each response schema is also scored by what it holds: how many properties, by name or
    description, use the vocabulary of employee, deposit, deduction or payroll data. An endpoint scoring
    3 or more in one of them needs a decision of its own, and the test fails until it has one. The score
    flags 49: the 3 benefits endpoints of A-91, fetched, and 46 decided one by one from their specs
    (billing, accounting, timekeeping, hiring, plan setup, open-enrollment workflow). It is a net for
    review, not a classifier: UKG documents 40 of its read endpoints without a schema, so those can't be
    scored.
- **Decision:**
  - `src/normalization/live/endpoints.py` records a decision for every documented read endpoint, and
    `tests/test_endpoint_inventory.py` fails when one in the five data types has none. The decisions:
    fetched, meaning the crawl requests it whenever the data to reach it exists; the same records as a
    fetched endpoint (another filter, a bulk or single form, a subset); a workflow step; configuration;
    unreachable from the demo scope; empty or refused when asked live; personal data the model
    deliberately doesn't hold (full SSNs, A-23); or a topic outside the five data types.
  - 20 endpoints beyond the original plan are fetched, each with live data:
    - PrismHR: `getHistory` (A-76), `getDependents` (A-77), `checkForGarnishments` (A-83),
      `getAllPrismClientContacts` (A-84), `getScheduledPayments` (A-80), `getRetirementLoans` (A-87), and
      `getRetirementPlan`, `getFlexPlans` and `getBenefitAdjustments` (A-91);
    - isolved: `/jobs` and `/categories` (A-76), `/contacts` (A-77), `/veteranStatus` (A-81) and the
      contact relationship lookup;
    - UKG: `/demographics` (A-79), `/contacts` (A-77), `/tax-info` (A-34), `/benefits` and position
      assignments (A-80), and the cost-center trees (A-75).
  - The coverage report also counts, per provider, how many employees have each canonical field
    ([docs/FIELD_COVERAGE.md](FIELD_COVERAGE.md)), so a gap like this shows at once: UKG gender was empty
    for 25 of 25 employees until `/demographics` was fetched.
- **Asked live and not fetched:**
  - empty for every employee asked: PrismHR deduction arrears, garnishment payment history, staffing
    placements, override and position rates, ACH deductions and custom field values; isolved benefit
    elections; UKG additional compensation and custom HR fields;
  - refused: isolved's period and year-to-date accumulations and Corestream payroll schedules (A-10);
  - the same data as a fetched endpoint: for example PrismHR `getEmployersInfo` (the employee record's
    employer, for all 35 employees asked), isolved `/eeoStatus` and `/disabilityStatus`, UKG total
    compensation, and isolved's per-employee check list, whose rows the crawl takes from the legal
    company's check list;
  - full SSNs, deliberately not called: PrismHR `getEmployeeSSNList` and isolved `employeesWithSSN` (4
    endpoints), which hold the only SSN digits PrismHR sends (A-23, A-50);
  - benefit enrollment: `getBenefitPlans` returns plans in every status, not only the active ones
    `getActiveBenefitPlans` returns. Asked for every fetched employee on 2026-10-16, 794 of its 1,002 plans
    were "eligible, not enrolled" and 32 terminated or waived. Enrollment and its history stay outside the
    five data types; the active plans, with their current employee contributions, are fetched.
- **Request options** count as well as endpoints: `getClientCodes` with `I9Docs`, asked live, only
  confirms the documented citizenship codes (A-45), and isolved's client details come with
  `includeDetails` (A-48).
- **Result:** of the 855, 80 are fetched (PrismHR 25, isolved 30, UKG 25), 63 return records already
  fetched, 4 return full SSNs and are not called, 24 are workflow steps, 203 are configuration or code
  lists, 11 are unreachable, 10 were empty and 2 refused live, and 458 belong to topics outside the five
  data types: benefit enrollment, time and attendance, hiring and documents, tax forms, the provider's own
  billing, and system plumbing. 167 of these decisions are made endpoint by endpoint. UKG's deduction
  detail is requested for each listed deduction, but the live tenant's list answers 404 (A-12), so live
  it never is.
- **Why:** "cover all available employee fields" is a statement about the provider's API, not about a
  plan. Only a check against the specs shows what was left out, and a test keeps it shown.

### A-85 The organizer's lookup references agree with the code tables
- **Evidence:** `contracts/<provider>/lookup-reference.json` lists 34 code domains, each with cited meanings.
  - PrismHR (8): client status class, service type, employee status class and the 12 deduction types match
    `providers/prismhr/codes.py` code for code and meaning for meaning; for example, client status `C`,
    "Client Cancelling, Pre-Termination", is `TERMINATING`. Payroll history type and the two hours-worked
    bases belong to responses not fetched (A-74). Benefit enrollment status is in the active benefit
    plans, which are kept on the employee (A-62).
  - isolved (11): timecard, scheduling and notification codes, in none of the fetched responses (time and
    attendance is outside the five data types).
  - UKG (15): every meaning is "None", the premise of A-26 and A-79. National ID type and payroll status
    are mapped from other documentation (A-57). The EEO, benefit-eligibility and payroll classifications,
    preferred phone and pay statement status are kept as sent, and time-entry type is outside the five
    data types.
- **Decision:** the code tables cite the specs directly, and the lookup files are a cross-check:
  `tests/test_lookup_references.py` fails when a PrismHR table maps a code its lookup domain doesn't list,
  or misses one it does, and when a UKG table maps a code its domain doesn't document.
- **Why:** they are the organizer's own cited references, so agreeing with them is a check on the
  mappings, and their UKG meanings show that UKG names its codes without defining them.

## Rules that apply everywhere

### A-64 Unknown, conflicting or failed source data is reported, never assumed
- **Decision:** wherever the data doesn't establish something, the output says so instead of assuming.
  Each case below has a regression test (`tests/test_audit_fixes.py`).
  - **Unknown kinds are not treated as cash.** A check that needs every line's kind reports "not
    applicable" when one is unknown (A-54), and UKG net pay isn't derived when a payment has an unknown
    `type_name` (`NET_PAY_NOT_DERIVED`, A-58).
  - **Conflicts are kept, not settled silently.** PrismHR elections from `getDeductions` and
    `getVoluntaryRecurringDeductions` match on their identity (code and dates), the same parts as the
    canonical ID. When the two disagree, the first is mapped, the other values are kept, and a
    `SOURCE_CONFLICT` warning names them. A loan is the same: `getDeductions` lists its repayment with the
    loan's ID and `getEmployeeLoans` the loan itself, so the two match on code and loan ID and become one
    election, with the loan's details. Live, both of the tenant's loans are listed in both, and one has a
    different start date in each, which the warning names.
  - **Zero is a value.** A UKG pay of 0 on a real compensation record is kept. Only the 1900-12-31
    placeholders, with no amount and 0 pay periods, are skipped, and their raw fields stay in
    `provider_extensions` (A-56).
  - **Not every number is an amount.** A provider "NaN" or "Infinity" is no value, like unparseable
    text, and a UKG lookup row without an `id` is skipped.
  - **Output is never half-written.** A SQLite export is built beside the destination and swapped in
    only on success. The exact-number JSON writer marks decimals with a random per-call token, so no
    source string can pass for a number.
- **Why:** a guess presented as data is worse than a gap that says so.

### A-70 Unavailable is not empty
- **Issue:** a request that returns no data must not look like the provider saying "none". UKG's
  deduction setup answers 404 for every employee (A-12); without a trace, those employees would seem to
  have no deductions. The FHIR standard keeps the same distinction, with a reason for every missing
  value.
- **Evidence:** failed requests mean different things.
  - isolved documents a 404 from many list endpoints as "nothing found", e.g. `/directdeposits`: "No
    employee direct deposits found." On the full fetch, 117 requests answer so, including 15
    direct-deposit, 43 garnishment, 45 contact and 11 job lists.
  - PrismHR's batch list answers 400 or 404 with "No batches exist for client ..." or "No batches could
    be found for the date range ..." (223 requests), and its scheduled payments 404 with "Scheduled
    payment for employee ... does not exist." (191). Its spec describes 400 and 404 only generically.
  - UKG answers cost-center tree 1 with 400 "Cost Center not used.", yet 8 employees are assigned cost
    centers in it, so that answer isn't taken as an empty tree (A-75).
  - UKG's deduction setup answers 404 "Unresolvable URL": a missing endpoint, not an empty list.
    isolved's 401s and PrismHR's 403s are refusals.
- **Decision:**
  - Every request is answered, empty or unavailable. It is empty only where the provider documents that
    status as "nothing found" (`EMPTY_RESPONSES` in its codes module) or says so in its message
    (`EMPTY_MESSAGES`). Every other failure is unavailable, including a PrismHR `errorCode` inside an
    HTTP 200.
  - An unavailable request becomes a `SOURCE_UNAVAILABLE` warning, with the status and what the provider
    said, on the records it would have fed: the employee its path or parameters name, otherwise its
    company. PrismHR employer lookups are keyed by employer, so the converter places those itself (A-09).
  - `summary.json` counts requests as answered, empty or unavailable, and lists the unavailable ones by
    endpoint and status. The CLI report has an "unavailable" column.
- **Result:** on the final fetch, 25 UKG employees say their deduction setup is unknown, the UKG company
  says its cost-center tree 1 is (A-75), and two isolved employees and one company carry its three
  refusals. The 117 documented and 414 stated empty answers raise nothing.
- **Why:** an empty list has to mean "none", or no empty list can be trusted.

### A-73 Missing is never read as zero, no or none
- **Issue:** the question of A-70, asked of every field: can "the provider didn't say" be told apart from
  "zero", "no" or "none"? A sweep normalizes each number and yes/no value in the synthetic scenarios
  twice, once deleted and once set to 0 or false. Identical outputs mean the two readings merged. It
  covers 432 fields, including numbers sent as text, as PrismHR sends most amounts.
- **Decision:**
  - **A flag that decides meaning is never defaulted, unless the provider documents the default.**
    isolved `isEmployeeTax` and `isMemoEarning` have none: if one is missing, a `FLAG_MISSING` warning
    says so and the value stays unknown (the tax's `paid_by` is `UNMAPPED`, the line's `in_gross` is
    null). PrismHR `usePercent` is documented "The default is False": a missing one means dollars, with a
    `DOCUMENTED_DEFAULT` note, as UKG contact role flags documented false by default are (A-77). One that
    isn't a yes/no leaves the amount as sent, with `FLAG_MISSING`. Live data sends all three on every
    line.
  - **A 0 that means "none" stays as sent** in `provider_extensions` instead of being used up: isolved
    and PrismHR rates (current and in the history) and annual pay, paper check amounts, hours worked, retirement
    catch-up, a garnishment's amount, percent or maximum, and benefit lines with nothing on the check. An
    employee left with no nonzero rate gets `NO_PAY_RATE`: 4 of 45 isolved employees (two contractors,
    one hourly and one salaried) and 9 of 194 PrismHR employees.
  - **A required line amount that wasn't sent** keeps a 0 stand-in, so the line's code and other values
    stay. The stand-in is marked derived, with a formula saying it wasn't sent, and an `AMOUNT_MISSING`
    warning says so too. A total that would include it isn't derived, and a check that would use it is
    not applicable. A garnishment with neither an amount nor a percent gets an `UNMAPPED` method, not a
    fixed amount.
  - **An unknown yes/no stays null.** `voided` is null where the provider sends no void indicator (isolved
    and UKG paychecks), and `is_remainder` is null when a deposit's method is unknown.
  - **A check an unknown value blocks** is reported as not applicable, with the reason, not left out.
  - **The other merges are reviewed** one by one in `tests/test_missing_vs_zero.py`, 94 of them, each with
    its reason: IDs (0 is never a real one), paging metadata, response envelopes, echoes of the request,
    code-table rows, list rows that their fetched detail replaces, and a second source repeating the
    first. A new merge fails that test until someone keeps the two apart or writes the reason down, and
    a reason that no longer applies fails it too.
- **Why:** a consumer must be able to trust that a zero was sent as a zero. The sweep only sees the code
  paths the scenarios exercise, so list-only rows have their own test.

### A-35 Customer-configured labels stay unmapped
- **Issue:** some values are names a customer chose, such as UKG employee type "FT Exempt" or the isolved
  category code "FT". No provider documents what they mean.
- **Decision:** they map to `UNMAPPED`, keeping the raw value and label, with no warning on each record.
  A mapping file can resolve them with evidence (A-65).
- **Why:** reading "full-time" out of a customer's naming is a guess, not evidence (model principle 3).

### A-23 Masking differs by provider; the output keeps at most the last 4 digits
- **Evidence:**
  - PrismHR SSNs come back fully masked (`***-**-****`), and so do its bank account numbers (all
    asterisks, no last 4). Birth dates come back **unmasked**, although
    `#/paths/~1employee~1v1~1getEmployee/get/description` says they are masked by default.
  - isolved returns full direct-deposit account numbers, and no SSN from the employee endpoint; its checks
    carry the last 4 (A-50).
  - UKG returns full SSNs. Its employee `photo_href` links each carry a signed token.
  - PrismHR `getEmployeeSSNList` and isolved `employeesWithSSN` return full SSNs.
- **Decision:**
  - SSNs and bank account numbers keep at most their last 4 digits **everywhere** in the output:
    canonical fields, `provider_extensions`, raw values and diagnostics. Values the provider already
    masked yield no last 4; nothing is invented.
  - A registry of sensitive source fields, plus a pattern sweep, enforces this. The registry includes
    PrismHR `cobraSSN` and UKG pay-info `bank_account_number`, and masks a value sent as a number as well
    as text. Diagnostics are swept as they're written. The pattern catches SSNs written 123-45-6789;
    nine digits without dashes aren't caught by it, because routing numbers and IDs look the same, so a
    sensitive field has to be in the registry.
  - The endpoints whose purpose is listing full SSNs are never called (A-74). PrismHR employees therefore
    have no last 4: `getEmployee` masks every digit. UKG's employee record itself carries the full SSN,
    which is masked on arrival like every other.
  - `photo_href` is dropped. Birth dates are kept as employee data.
- **Why:** keeping fields verbatim in `provider_extensions` would otherwise undo the masking. Calling an
  endpoint to receive full SSNs, only to keep 4 digits of each, isn't worth the exposure on a live system.
  Commercial payroll APIs make the same call: Finch returns SSNs only to an application granted a
  separate permission that asks for them on each request.

### A-25 Open-ended dates and span boundaries
- **Evidence:** UKG `reference-docs/Foundations.html` ("Conventions related to time") documents
  "beginning of time" = **1900-01-01** and "end of time" = **3000-01-01**, and says effective dates are
  inclusive and expiration dates exclusive. 1900-12-31 is the earliest date UKG accepts: its
  reference schemas describe date fields as "within the 1900-12-31 and 2079-06-05 date range" (299
  times). 9999-12-31 appears only in documentation samples. Neither is documented as open-ended. 2099-12-31 appears live, on every UKG deposit.
- **Decision:**
  - Only 1900-01-01 and 3000-01-01 become null (open-ended), with the raw value kept, and only on UKG
    span fields.
  - Other far-off dates are kept as real dates with an info diagnostic. On UKG, a date at or beyond the
    documented range (1900-12-31, or after 2079-06-05) gets `UNDOCUMENTED_SENTINEL_DATE`. Live, every UKG
    employee's pay history has a row effective 1900-12-31; it keeps that date, though it may well mean
    "since the start" (A-56).
  - UKG spans are evaluated as `from <= as_of < to`.
  - PrismHR and isolved document no span semantics, so their end dates are treated as inclusive. This is
    an assumption, noted in diagnostics.

### A-29 Percent scale (5 vs 0.05)
- **Rule:** a scale is proven only by arithmetic on the provider's own amounts, never by how large a value
  is. The organizer's reference audit says not to infer units from a numeric value's magnitude.
- **Evidence:**
  - PrismHR deductions with `usePercent = true`: on the final fetch, all 19 such elections (every one a
    401(k)) match their paycheck lines exactly: deducted amount = percent ÷ 100 × the voucher's retirement
    base earnings, on 214 of 214 lines.
  - Live direct deposits: PrismHR has one P deposit (10.00) and isolved three percent deposits (30.0, 1.0
    and 1.0), but none of their owners has a fetched paycheck, so nothing shows how the percent is applied.
  - isolved deduction "Percent" parameters are all 0.0, and no UKG percent was seen live.
- **Decision:**
  - PrismHR deduction percents are verified percentage points: `scale: VERIFIED_POINTS`, with `percent`
    set.
  - Every other percent keeps its raw value with `scale: UNVERIFIED` and `percent: null`: all deposit
    percents, PrismHR employer match percents, isolved deduction percents and all UKG percents. No
    converted number is published for them.
  - Synthetic fixtures cover percent allocations.
- **Why:** a warning next to a possibly wrong number still lets a consumer use the wrong number.
  Withholding the conversion makes the uncertainty impossible to miss.

### A-31 Currency
- **Decision:** UKG states its currency, so it is used as given, and a UKG deposit's amount is in the
  deposit's own `currency`. PrismHR and isolved state none, and their amounts are recorded as USD.
- **Why:** both are US payroll systems with federal and state tax lines. The assumption is applied in one
  place and is easy to change.

### A-33 Time-dependent fields use an explicit `as_of` date
- **Decision:** values like "is this deposit active?" (UKG `active` plus dates) are evaluated against
  `as_of`. That date defaults to the fetch date for live data (`session.json` `saved_at`) and is fixed for
  fixtures (`session.json` `as_of`). A deposit's status evaluation leaves an `EVALUATED_AT_AS_OF`
  diagnostic; the choice of UKG's current pay record shows in the record's `effective_date`, with every
  other record in `history`. A missing date gives `AS_OF_UNKNOWN` instead of a guess.
- **Why:** the output must be reproducible, so it can't depend on today's date.

### A-59 One amount arrived as a binary floating-point number
- **Evidence:**
  - One live UKG tax amount is `2.4699999999999998`: 2.47 after a binary floating-point computation.
  - The pay statement page types `ee_amount` as a float, and says "Amount should be rounded to a Penny".
  - Such values are rare: 1 of 988 UKG decimals in the first sample and 3 of 2,555 in the second UKG
    fetch, against 0 of 31,602 PrismHR and 0 of 8,387 isolved decimals.
- **Decision:** keep it exactly as sent, never rounded, with a `FLOAT_ARTIFACT` info diagnostic that
  names the penny amount. Derived sums carry it too, and the checks' 0.01 tolerance absorbs it.
- **Why:** rounding would be a guess about the provider's intent. Reporting it lets a consumer decide.

## Company

### A-30 A company is the business, not the legal employer
- **Evidence:** PrismHR `#/components/schemas/ClientMaster/properties/serviceType` (PEO, ASO, ...) and
  `.../employerId` ("employer ID to which to assign this client's employees") are documented separately
  from `federalIdNumber`. Across the 25 live clients (18 PEO, 5 ASO, 2 COR):
  - employer 5 is shared by PEO, ASO and COR clients;
  - two ASO clients' employer IDs equal their own client IDs;
  - `federalIdNumber` is masked (23 clients) or empty (2).
- **Decision:** a company is the business the employees work for: a PrismHR client, an isolved legal
  company (with its client as the parent), a UKG company. Service arrangement, assigned employers and the
  company's own tax ID are separate fields, and none is labeled "employer of record for taxes".
- **Why:** the data cannot tell us who files the taxes, so we record what each provider says, in its own
  terms.

### A-09 PrismHR employer names and EINs are refused
- **Evidence:** `system/v1/getEmployerDetails` returns 403 for all six referenced employer IDs (A-05).
- **Decision:** a company's `employers[]` keeps the employer IDs only, and the name and EIN stay null. The
  company carries a `SOURCE_UNAVAILABLE` warning saying so (A-70).

### A-15 UKG has no company details endpoint
- **Decision:** the UKG company's name and address stay null. Its EINs come from `lookup/eins` (A-60).

### A-60 UKG EINs: the lookup doesn't list them all
- **Evidence:** `lookup/eins` returns one EIN. The 89 live payrolls name two: the listed one (46 payrolls)
  and a second one (43), each with its name and tax ID. All 15 employees of the first sample name the first.
- **Decision:**
  - The company's `employers[]` holds every EIN from the lookup, plus any EIN only payrolls name, with an
    `EIN_FROM_PAYROLL` info diagnostic.
  - Employees and payroll runs carry the EIN as `legal_entity_id`.
  - With several EINs there is no single `own_tax_id`, so it stays null.

### A-84 PrismHR company contacts
- **Evidence:** `getAllPrismClientContacts` (`#/components/schemas/PrismClientContact`): name, title, phone
  and extension ("contact's telephone number"), mobile, email and address, with a contact type "specified
  by the service provider". Live: 10 contacts at 7 of the 25 clients, typed O (3), CONTR (3), PAY (2), P
  and HR.
- **Decision:** `company.contacts[]` holds each contact's name, title, contact type as sent, phones (`MAIN`
  and `MOBILE`) and email. Addresses and comments are kept.
- **Why:** company data includes who to contact at the company; the contact types are the PEO's own codes.

## Employee

What is normalized: identifiers, name, personal details and contacts, addresses, phones and emails,
employment status and dates with their history, job and organization with their history, and
compensation with its history. Every other field is kept unchanged (sanitized, A-23) in the record's
`provider_extensions`, and the field coverage report shows each field's fate (A-62). The kept fields are
mostly tax withholding setup (A-34), onboarding and compliance flags, benefit-group memberships, and
provider bookkeeping such as checksums and last-change dates. For PrismHR's employee response, 74 fields
are normalized and 130 kept; isolved's, 45 and 67; UKG's, 36 and 29. A few more are dropped for a stated
reason, such as PrismHR's copy of the scheduled deductions its own endpoint returns (A-62).

The coverage report also counts how many employees have each canonical field, per provider (A-74). Its
zeros on the full fetch:
- **Not sent by the provider:** UKG marital status, veteran and disability status, FLSA status and pay
  group; isolved start and seniority dates, and per-employee employer IDs (isolved's employer is the
  legal company itself, A-30).
- **Kept elsewhere:** isolved and UKG organization is in `job.org_units`, not `department` (A-75).
- **No evidence to map:** UKG worker classification (A-34).
- **None in these employees:** UKG has no employment history beyond compensation, isolved contacts are
  empty (A-77), and no sampled UKG employee is terminated.

### A-48 isolved employment status: through the client's status table
- **Evidence:**
  - `#/definitions/AOS.PayrollOffice.RestAPI.Models.EmployeeModel/properties/employmentStatus` is "The
    current employment status description", with no list of values.
  - The organizer's reference audit says "isolved reads employment statuses from client details".
    `/api/clients/{id}` with `includeDetails=true` ("full client details") returns the client's
    `employmentStatuses` (`ClientEmploymentStatusModel`): each has a code, a description and a
    `payrollStatus`, "An object that holds a system's payroll status". Live, the demo client lists A
    Active, I Inactive and T Terminated, each tied to the system status of the same name.
  - `/employees/{e}/statuses` (`EmployeeEmploymentStatusModel`) marks each history row with
    `isImpliedStatus`. All 31 live rows are implied: "Active" (30) and "Terminated" (1), which are also the
    only two live `employmentStatus` values.
- **Decision:** a status maps through the system payroll status the client's table ties it to: Active to
  `ACTIVE`, Inactive to the new `INACTIVE`, Terminated to `TERMINATED`. Those system statuses are
  isolved's own, so their meaning is fixed. A customer status, such as "Leave - FMLA" tied to Inactive,
  takes its system status, with a `SYSTEM_STATUS` note, and keeps its own name as the label. A status
  the table doesn't list maps only when its history shows it as an implied system status; otherwise it
  stays `UNMAPPED` with a `CUSTOMER_STATUS` note. Status history maps the same way (A-76).
- **Why:** the client decides which system status each of its statuses belongs to, so that link is
  evidence; reading "on leave" from a status's name would not be (A-35).

### A-89 PrismHR status and type: the documented class, not the client's code
- **Evidence:** PrismHR employees carry two status fields and two type fields. `client.statusClass` and
  `client.typeClass` are PrismHR's documented classes (A/L/T, F/P). `client.employeeStatus` and
  `client.employeeType` are the client's own codes from its code tables. The organizer's reference audit
  calls them "separate domains" that candidates "must preserve". Live, the type code (FT, PT) differs from
  the class (F, P) for all 194 employees.
- **Decision:** the class maps to the canonical status and type. The client's code stays as sent in
  `provider_extensions`, and its description is not attached to the class: a client code's label
  describes the code, not the class. History rows keep the client code as their raw value (A-76).
- **Why:** the two are separate domains, so each keeps its own value. A class labeled with a client code's
  description would mix them: class F labeled "Seasonal", the description of code S.

### A-55 UKG employee status
- **Evidence:** `#/schemas/106` documents `status` only as "This field is only used for GET". Live,
  "Terminated" appears exactly when `dates.terminated` is set (12 of 12), and "Active" exactly when it
  isn't (3 of 3).
- **Decision:** "Active" and "Terminated" map to `ACTIVE` and `TERMINATED`. Anything else stays
  `UNMAPPED` with its text.

### A-44 PrismHR gender codes
- **Evidence:** `#/components/schemas/Person/properties/gender` lists "M, F, X or D" without meanings.
  `#/components/schemas/NewHireEmployee/properties/gender`, the same field when an employee is created,
  defines them: "'M' (male), 'F' (female), 'X' (non-binary), 'D' (declined) or 'U' (unknown)". Live: M 94,
  F 89, none 11.
- **Decision:** M, F, X and D map to `MALE`, `FEMALE`, `NON_BINARY` and `DECLINED`. U, which Person
  doesn't list, would stay `UNMAPPED`: the canonical enum has no "unknown", since an unknown gender is a
  missing one.

### A-45 PrismHR citizenship arrives as the documented description, not the code
- **Evidence:** `#/components/schemas/Compensation/properties/citizenshipStatus` documents codes Z01–Z04
  with their meanings. All 18 values in the first sample are the description text itself, e.g. "A
  citizen of the United States". On the full fetch, 45 employees have `Y`, which is neither a documented
  code nor a description.
- **Checked live (2026-10-15):** `NewHireEmployee/citizenStatus` says the "Allowed values can be obtained
  by calling ClientMaster.getClientCodes with 'I9Docs' option". Asked for all 25 clients, that table
  (sent as `citizenshipStatusCode`, documented as `citizenshipStatusCodes`) holds exactly Z01–Z04 with the
  documented descriptions, in every client. `Y` isn't a client code either.
- **Decision:** both the codes and their exact documented descriptions map to the canonical values.
  Anything else stays `UNMAPPED`, including `Y`, whose meaning isn't documented. The I9Docs table isn't
  fetched routinely: it only repeats the documented list.

### A-39 Contractor status is not a pay type
- **Evidence:** PrismHR `#/components/schemas/Client/properties/employee1099` is independent of
  `#/components/schemas/Compensation/properties/payMethod`. isolved puts "1099" inside `payType`.
- **Decision:** employees get a separate `worker_classification` (`EMPLOYEE`/`CONTRACTOR_1099`). isolved
  "1099" sets it, and leaves `pay_type` `UNMAPPED`. isolved's pay type lookup also has "1099 (Hours
  Based)", which sets it with pay type `HOURLY`. "1099R" doesn't: a 1099-R reports retirement
  distributions, not contract pay. The lookup's "Salary-Exempt" and "Hourly - Exempt" map like "Salary
  Non-Exempt", to the pay basis they name; its other descriptions (Draw, Piecework, Guarantee, ...) stay
  `UNMAPPED` for a mapping file.

### A-50 isolved SSN last 4 comes from check records
- **Evidence:** `EmployeeModel.ssn` is required ("Employee SSN or identification type value") but is null
  on all 30 employees in the first sample. `CheckModel.employeeSSN` ("Employee Social Security Number")
  arrives masked as `XXX-XX-` plus the last four digits, on all 430 listed checks and all 15 check details.
- **Decision:** when the employee record has no SSN, `national_id.last4` comes from the employee's checks,
  with `source_field` `checks[].employeeSSN` and `masked_at_source` true. Employees with no fetched check
  have no national ID: on the full fetch, 21 of 45 have one.
- **Why:** the last four digits are all any record keeps (A-23). isolved's `employeesWithSSN` endpoints
  return the full SSN; they are deliberately not called (A-23, A-74), which leaves checks the only source
  of the last 4.

### A-20 PrismHR `salary` is per pay period
- **Evidence:** PrismHR `#/components/schemas/Compensation/properties/salary` documents it.
  - Live, `salary × pay periods per year = annualPay` for all 29 salaried employees (W=52, B=26, M=12).
  - For all 22 hourly employees, `annualPay = hourlyPay × 2080`.
- **Decision:** `salary` is a rate per `PAY_PERIOD`. `annualPay` is kept as a provider-calculated figure.
  For hourly employees it is an assumed 2080-hour year, not a contract amount, and is labeled that way.

### A-19 PrismHR pay-rate basis `A` is undocumented; it behaves as annual
- **Evidence:** PrismHR `#/components/schemas/Compensation/properties/hourlyPayPeriod` documents
  H/W/B/S/M/Y. Live, 18 employees have `A`, and on all 18 `hourlyPayRate` equals `annualPay`. The
  documented `Y` behaves the same way (1 of 1). The pay-rate history schema documents `A` as "annually"
  (`#/components/schemas/PayRate/properties/payPeriod`).
- **Decision:** map `A` to per `YEAR`, keep the raw value, and add an info diagnostic.
- **The mirror case:** the pay-rate history's `PayRate/payPeriod` documents `A` but not `Y`, and live
  sends `Y` on 26 history rows, on every one of which `payRate` equals `annualPay`. `Y` is documented as
  "(Y)early" in `hourlyPayPeriod`, so it maps to per `YEAR` the same way, with the same diagnostic.

### A-27 isolved pay frequency: resolved by description, never by ID
- **Evidence:** `#/definitions/AOS.PayrollOffice.RestAPI.Models.LookupFrequencyModel/properties/id`
  defines the ID only as a "Unique Object Id".
  - Live `/api/lookup/Frequencies` has descriptions such as Monthly, Semi-Monthly, Bi-Weekly, Weekly and
    "N Pay Periods Per Year".
  - The live IDs happen to equal those counts (12, 24, 26, 52), but nothing promises that.
- **Decision:** `payFrequency` is resolved through the lookup, and the *description* maps through a fixed
  table: Weekly = 52, Bi-Weekly = 26, Semi-Monthly = 24, Monthly = 12, Quarterly = 4, Annually = 1,
  "N Pay Periods Per Year" = N. The ID is never used as a count. Unknown descriptions map to `UNMAPPED`.

### A-56 UKG pay: amounts, hours and pay periods
- **Evidence:**
  - `#/schemas/122` gives each compensation record an `amount` per `amount_period`, an `hourly_pay`, a
    `time` per `time_period` ("Time is represented in milliseconds") and `num_pp_in_year`.
  - Live, all 27 records with an amount agree: `amount` ÷ hours per period = `hourly_pay`. For example, a
    YEAR amount ÷ 2080 hours (7,488,000,000 ms) gives the hourly pay, and so does a PAY_PERIOD amount × 26
    periods ÷ 2080 hours.
  - Every employee's history also has a record effective 1900-12-31, the earliest date UKG accepts (A-25).
    On the final fetch, 6 of the 25 are placeholders, with no amount and `num_pp_in_year` 0; 17 carry
    pay, and 2 a pay of 0 over 26 pay periods, which is kept as a value (A-64).
  - `lookup/pay-types` is documented with the sample names "Pay Type 1" and "Pay Type 2", so pay types are
    customer-defined; live they are "Hourly" and "Salaried". Employee types ("FT Exempt", "Consultant")
    are customer-defined too.
- **Decision:**
  - The current pay is the latest record in effect at `as_of` (A-33). Every record is kept in `history`,
    including records dated after `as_of`. A real pay of 0 is kept; only the placeholders are skipped
    (A-64).
  - Rates keep their period, and `hourly_pay` is added as a rate per hour. `time` becomes standard hours,
    derived, with the raw milliseconds kept, per `time_period`. Pay-info `standard_work_day`, documented
    in milliseconds (the organizer's reference audit cites it), becomes `compensation.standard_work_day`
    in hours, derived, with the raw value kept: 8 hours for every live employee.
  - `num_pp_in_year` sets the pay frequency: 52 is weekly, 26 biweekly, 24 semimonthly, 12 monthly,
    because each count is that frequency's definition. Any other count is `OTHER` with the count, and 0
    means not set.
  - Pay type and employee type stay `UNMAPPED` with their names (A-35).
  - The arithmetic covers the three periods seen live: HOUR (27 records), YEAR (33) and PAY_PERIOD (10).
    `WEEK` and `MONTH` are documented without a definition and never seen, so a rate in one is `UNMAPPED`,
    with an `UNMAPPED_CODE` warning and the period kept as sent (A-26).

### A-46 PrismHR placeholder dates
- **Evidence:** live `compensation.effectiveDate` and pay-rate history contain `0000-01-01`, which is not
  a valid date. Pay-rate history also contains `9999-12-31`. Neither is documented.
- **Decision:** `0000-01-01` becomes null with an `INVALID_DATE` warning. `9999-12-31` is kept as a date
  with an info diagnostic, consistent with A-25. Nothing is guessed.

### A-34 Tax withholding setup is kept, not normalized
- **Issue:** each provider exposes federal and state withholding settings (filing status, allowances,
  extra withholding) in a different shape. Normalizing them would be a sizable model of its own.
- **Decision:** they are kept unchanged in `provider_extensions`, with no canonical tax-setup fields. PrismHR
  and isolved send them with the employee; UKG's come from `/tax-info` (A-74). Its
  W-2, 1099 and draw flags have no definitions (`#/schemas/166`), so UKG's `worker_classification` stays
  empty rather than being read from their names (A-26).
- **Why:** nothing is lost, and the time went to the required data first. This is the largest group of
  employee data left unnormalized.

### A-75 Organization units keep the provider's own names
- **Issue:** isolved and UKG let each customer define its organization: which dimensions exist and what
  they're called. isolved's employee record lists them in `organizations[]`; UKG's carries only IDs
  (`cost_centers_info`). Neither fills a fixed field such as `job.department`.
- **Evidence:**
  - isolved `#/definitions/AOS.PayrollOffice.RestAPI.Models.EmployeeOrganizationModel`: `title` is the
    "Title of the client organization field", `value` its lookup code and `valueDescription` its
    description. Live, 31 of 45 employees have two: "Location" and "Department".
  - UKG `config/cost-centers` (`#/schemas/45`) lists one tree per `tree_index`, 0 to 8, and a tree's "root
    node has only `id` and `name`" (the cost-center page). Live, the trees are named "Location-Dept",
    "Position", "Default Settings", "Stipend", "Job Codes", "Certified Jobs", "Work Classification" and
    "Grants". Every employee cost center at index *i* that resolves is a node of tree *i* (41 of 41). The
    other 8 point at tree 1, which answers HTTP 400 "Cost Center not used.": the answer and the employees
    disagree.
- **Decision:**
  - `job.org_units[]` holds each assignment as {`dimension`, `code`, `name`, `path`}. `dimension` is the
    provider's own name: the isolved title, or the name of the UKG tree's root. It is never interpreted: a
    dimension called "Department" isn't copied into `job.department`.
  - A UKG cost center is named from its tree, with the path of names from below the root down. An ID no
    tree holds keeps its ID, with a `COST_CENTER_UNRESOLVED` warning.
  - Tree 1's "Cost Center not used." is unavailable data, not an empty tree (A-70): 8 employees use it.
- **Why:** the brief asks for organization details, and these are them. The dimension names are customer
  configuration, so mapping them onto canonical department or location would infer meaning from labels.

### A-76 Employment and job history
- **Issue:** an employee's status, job and organization change over time, and current values alone lose
  that.
- **Evidence:**
  - PrismHR `getHistory` (`#/components/schemas/HistoryRecord`) holds one change per row, in an object
    named for its kind (`statusChange`, `leave`, `termination`, `departmentChange`, ...) or as a
    `newPositionCode`. Status and type codes are defined by the service provider; the client's code table
    gives each its documented class (`statusCode[].statusClass` A/L/T, `typeCode[].typeClass` F/P), the
    classes the current status maps from. Live, the 194 employees have 776 rows: 361 pay, 203 position, 194
    status, 10 benefit-group and 8 termination changes.
  - isolved `/jobs` (34 of 45 employees; "No Employee jobs found." for the other 11) and `/categories`
    (45 of 45), plus `/statuses`, which was fetched but only kept.
- **Decision:**
  - `employment.history[]`: status, leave, termination and employment category changes, each with its
    effective and end dates, status, employment type, reason and expected return date.
  - `job.history[]`: job and organization changes, each with title, job code, department, division,
    location, organization units, manager, supervisor and reason.
  - PrismHR codes map through the client code table's class. isolved statuses map as the current one does
    (A-48), and its categories are customer codes (A-35).
  - PrismHR pay changes stay kept: compensation history comes from `getPayRateHistory`, and mapping both
    would repeat each change. Benefit-group and wellness changes stay kept too.
- **Why:** "employment status and dates" and "job details" have a history, and the providers expose it.

### A-77 Contacts: emergency contacts, dependents and beneficiaries
- **Issue:** PrismHR sends emergency contacts with the employee and keeps dependents and beneficiaries in
  `getDependents`; isolved and UKG keep contacts in an endpoint of their own.
- **Evidence:**
  - UKG `employees/{aid}/contacts` (`#/schemas/124`): `emergency`, `dependent` and `beneficiary` flags,
    each with a default of false, behind the documented `contact_type` filter "EMERGENCY, DEPENDENT,
    BENEFICIARY". Live: 19 contacts for 11 of 25 employees.
  - isolved `PersonContactModel`: "Contact Is Emergency Contact", "Contact Is A Dependent", "Contact Is A
    Beneficiary", and an emergency call order. Live, "No contacts found" for all 45 fetched employees, so
    this mapping rests on the documentation and the fixtures.
  - PrismHR `#/components/schemas/Dependents`: `relationType` 'D' (Dependent) or 'B' (Beneficiary only),
    `beneficiaryType` 'P' or 'C', and `status` 'A', 'I' or 'P'. Live: 14 dependents of 8 of the 194
    employees, besides 33 emergency contacts. 12 of the dependents' birth dates arrive masked
    (`****-**-**`).
- **Decision:** `personal.contacts[]` holds all of them. Each contact has its `roles`, name,
  relationship in the provider's own words (and its code, when it has one), primary flag, priority, birth
  date, phones, emails, address and active flag. PrismHR's emergency contacts keep their single value and
  its kind (`contact_type`, `contact_info`). A missing UKG role flag is false, as documented; a missing
  isolved one leaves the role unknown, with `FLAG_MISSING` (A-73). A birth date the provider masked is not
  a malformed date: it stays as sent, with a `MASKED_AT_SOURCE` note. Contacts' SSNs keep only their last 4
  (A-23), isolved's unmasked copy included.
- **Why:** emergency contacts are profile data. Two of the three providers list dependents and
  beneficiaries as the same records, so splitting them would be arbitrary.

### A-79 UKG demographics stay UNMAPPED until a mapping file confirms them
- **Evidence:** `employees/{aid}/demographics` (`#/schemas/134`) documents gender (MALE, FEMALE, UNDEFINED;
  default UNDEFINED), citizenship (US_CITIZEN, PERMANENT_RESIDENT, ALIEN_WITH_WORK_PERMIT,
  NONCITIZEN_NATIONAL_OF_US) and ethnicity as enums without definitions, and no response labels them.
  Live: gender for 25 of 25 employees (FEMALE 12, MALE 11, UNDEFINED 1, and NON_BINARY 1, which isn't
  documented), ethnicity for 23 and citizenship for 12.
- **Decision:** as for UKG deposit methods (A-26): no label, no mapping. Gender and citizenship are
  `UNMAPPED`, with the value as sent and an `UNMAPPED_CODE` warning. Ethnicity is a coded value with its
  raw, as for the other providers. The review queue lists them with suggestions (A-66). A reviewed
  mapping file confirms the plain values for the demo tenant: MALE, FEMALE, NON_BINARY and the four
  citizenship values; UNDEFINED stays `UNMAPPED` (A-86). Visa type and dates are kept; the visa number
  keeps only its last 4 (A-23).
- **Why:** the names look self-explanatory, but the same rule kept `NET_PAY` from being guessed (A-26), and
  it can't make exceptions by how obvious a name looks. The values are there, with their source.

### A-80 Responses about an employee that no record type holds are kept with it
- **Decision:** PrismHR scheduled payments (recurring payments set up for future payrolls), UKG tax setup
  (A-34), benefit plans and position assignments are fetched for every employee and kept as sent in the
  employee's `provider_extensions`. Live: PrismHR scheduled payments for 3 of 194 employees, and UKG
  benefit plans for 18 and position assignments for 6 of 25.
- **Why:** they are employee data that none of the brief's types has a record for. Kept, they are
  available and traceable; normalizing them would mean new record types.

### A-81 isolved veteran and disability status
- **Evidence:**
  - `EmployeeModel/properties/disabled` is "True = Disabled, False = Not Disabled", and
    `disabilityDescription` "a text description of the current disability status". Live, 2 of 45 employees
    have no `disabled` value and the description "Chose not to answer": the words the genders lookup uses
    for a declined answer.
  - `protectedVeteran` ("the employee is a protected veteran"), `isRecentlySeparatedVeteran`, and
    `/veteranStatus`'s three "if the person is a protected veteran with ..." flags are false for all 45
    fetched.
    `/veteranStatus`'s text has no documented values; live it is "NoAnswer" for the same 2 employees.
  - `veteranStatusNotSpecified` is documented as "a veteran of unspecified status", but live it is true
    exactly for those 2 employees: the documentation and the data disagree.
- **Decision:** disability maps from `disabled`, or, when that is empty, from the description ("Chose not to
  answer" is `DECLINED`). Veteran is `YES` when a documented veteran flag is true; otherwise
  `/veteranStatus`'s text is `UNMAPPED`, with the value as sent. `veteranStatusNotSpecified` stays kept
  (A-64). `/disabilityStatus` and `/eeoStatus` aren't fetched: they repeat the employee record.
- **Why:** the model has fields for both, and each value is mapped only as far as its evidence goes.

### A-82 UKG mailing address and second email
- **Evidence:** the employee record (`#/schemas/106`) has `mailing_address`, an address, with
  `use_separate_mailing_address`, and `secondary_email` next to `primary_email`. Live: 1 of 25 employees has
  a mailing address (and the flag), 14 a second email.
- **Decision:** the mailing address is an address of type `MAILING`. The second email is an email of the
  new type `SECONDARY`: ranked second by the provider, with no stated purpose, where `MAIN` is the first.
  The write path sends a `SECONDARY` email back as UKG's `secondary_email` (A-63).
- **Also:** UKG's `nickname` is `name.nickname`, as PrismHR's is; `name.preferred` holds a preferred name
  (PrismHR and isolved `preferredName`). isolved's override address, `EmployeeW2OverrideAddressModel` ("for
  use in tax forms or pay checks"), is typed `W2`, as PrismHR's W-2 address is, not `MAILING`.
- **Why:** the model has fields for both; the type says only what UKG says.

## Direct deposits

### A-37 HSA deposits are a different kind of deposit
- **Evidence:** in PrismHR `#/components/schemas/EmployeeDirectDeposit-HsaDepositSettings`, `method` PN
  means "Percent of Net after Taxes", while in an ordinary `AchVoucher` it means "percentage of net after
  fixed". HSA account types HE/HES/HC/HCS also encode who funds the deposit (employee or company) and the
  destination (checking or savings).
- **Decision:** deposits carry `purpose` (`NET_PAY` or `HSA`) and, for HSA, `funding`. Methods are mapped
  per full source field, so the two `PN` values get different canonical methods.

### A-26 UKG direct-deposit methods: only labeled values are mapped
- **Evidence:** UKG `#/schemas/137` lists the `calc_method.type` values with no descriptions. The cached
  response samples label `FULL` "Entire/Remainder", `FLAT_AMOUNT` "Flat Amount" and `GROSS_EARNING` "% Of
  Gross Earnings". Live data shows only `FULL` ("Entire/Remainder"). `NET_PAY` and
  `DIRECT_DEPOSIT_PER_OF_REMAINDER` have no label anywhere.
- **Decision:** `FULL`, `FLAT_AMOUNT` and `GROSS_EARNING` map to `REMAINDER`, `FIXED_AMOUNT` and
  `PERCENT_OF_GROSS`. `NET_PAY` and `DIRECT_DEPOSIT_PER_OF_REMAINDER` map to `UNMAPPED`, keeping the raw
  type and its `display_name`, and such a deposit's `is_remainder` is null (A-73).
- **The same rule, everywhere:** a code maps only where the provider defines it: a description, a label in
  a response or sample, a documented process that produces it, or live evidence. So these stay `UNMAPPED`
  too, however plain their names; the rule makes no exception for a name that looks obvious (A-79):
  - UKG deposit `account_type` (CHECKING, SAVINGS) and deposit `type` RESERVE_LIVE_CHECK;
  - UKG rate periods WEEK and MONTH (A-56) and payroll statuses `*_FAILED` (A-57);
  - isolved garnishment `limit`, documented only as "Limit" (A-88).

  A person can still confirm a plain name, in a reviewed mapping file with the reason written down
  (A-86); the demo tenant's file confirms CHECKING, SAVINGS and RESERVE_LIVE_CHECK.
- **Why:** enum names are the provider's words but carry no definition. Labels are evidence; names alone
  are not. The brief's own reference files take the same line: "undocumented meanings remain unknown"
  (README), and "Per-code meanings are not inferred from enum labels" (UKG lookup reference).

### A-14 UKG's deprecated direct-deposit endpoint still works
- **Evidence:** the docs show the endpoint was deprecated 2023-04-13, with enforcement for "new
  customers" from 2026-01-29 (`Deprecation and Versioning.html`). Live, every call returns 200 (25 of 25
  on the full fetch). The endpoint page lists `X-End-of-Support-Timeline` as a required *request* header
  (default 2026-01-29), while `HTTP Headers.html` describes it as a *response* header.
- **Decision:** send the documented default and record what happens. The endpoint can stop working at
  any time; that is a known limitation.

## Deductions

### A-41 Deduction calculations keep their basis
- **Evidence:** PrismHR `#/components/schemas/DeductionCodeDetail/properties/calculationMethod` documents
  29 methods. They distinguish gross pay from gross earnings, hours worked from hours paid, and percent
  from per-ten-thousand, and some round to the dollar.
- **Decision:** a calculation is {method, basis, value, rounding}, mapped code by code (model §7).
  Providers that give no basis (isolved, UKG) get `UNSPECIFIED`.

### A-49 isolved deduction categories come from the client pay item's system classification
- **Evidence:**
  - Employee pay items (`EmployeePayItemModel`) have a name, code and type ("Deduction", "Earning", "Memo
    Calc") but no category. Client pay items (`ClientPayItemModel`) add `systemBenefitType` and
    `systemPayItemType`: the system item the client's item is built on. The spec describes them only as
    "System Benefit Type" and "System Pay Item Type".
  - Live, all 1,845 employee pay items on the full fetch (225 earnings, 855 deductions, 765 memo
    calculations) link to a client pay item by title (`payItemName` = `title`). Titles are unique per
    client (56 of 56) but codes are not (41 distinct codes across 56 items), so linking by code would pick
    a different item for 540 of the 1,845. `payItemId` is documented as deprecated and matches no client
    item ID; it is kept as sent.
  - Most of those rows are the client's catalog, not the employee's choices. All 45 employees list the
    same 19 deduction items under the same 19 negative IDs, so those IDs identify no stored row, though
    the spec calls `id` a "Unique Object Id". Those 848 rows have no start or stop date and only zero
    values. The 7 rows with real IDs have start dates, and 6 of them an amount. Every earning and memo
    row has a negative ID too, and 45 of the earning rows carry real values, so a negative ID alone
    doesn't make a row a catalog entry.
  - Check lines link the same way. On all 154 live earning and deduction lines, `itemDescription` is a
    client item's title and `itemCode` is that item's code. Garnishment lines (4) don't link.
- **Decision:**
  - Category and tax treatment come from a table keyed by (`systemBenefitType`, `systemPayItemType`) in
    `providers/isolved/codes.py`. For example, ("401(k)", "401K Loan") is a `RETIREMENT_LOAN`, and
    ("Dental Pre-Tax 125", any type) is a pre-tax `SECTION_125` deduction.
  - A system pay item type that says "post-tax" or "after-tax" sets the treatment to post-tax.
  - Unknown pairs stay `UNMAPPED`, with the pair kept as the raw value.
  - A "Deduction" item becomes an election unless it is a catalog row: a negative ID and only zero
    values. Live, 7 remain. Catalog rows, earning and memo items stay in the employee's
    `provider_extensions`.
  - Garnishments are always `GARNISHMENT`. The garnishments endpoint's documented 404, "No employee
    garnishments found", means none (A-70).
- **Why:** the system types are isolved's own classification. Titles are customer-chosen text (A-35).

### A-12 UKG deduction setup: documented, but this tenant answers 404
- **Evidence:** UKG documents employee deduction setup in `#/schemas/132` (list) and `#/schemas/133`
  (detail): frequencies, annual limits, calculation methods and dates. The demo tenant answers 404
  "Unresolvable URL" for every employee (25 on the full fetch).
- **Decision:**
  - The UKG converter supports the documented endpoints and is tested on synthetic data. For this tenant
    there are no UKG `DeductionElection` records, and each employee carries a `SOURCE_UNAVAILABLE`
    warning, so their deductions read as unknown, not none (A-70). Deductions still appear on pay
    statements.
  - `annual_max_amount` and the calculation `amount` fields are typed integer, and nothing says whether
    they are dollars or cents. They stay raw in `provider_extensions`, with an `AMOUNT_UNIT_UNVERIFIED`
    diagnostic. The calculation method is an open string, so it stays `UNMAPPED` with its `display_name`.
- **Why:** a tenant's missing endpoint is a fact about the tenant, not about UKG, and the converter
  shouldn't be limited by one demo account.

### A-08 PrismHR garnishment details are refused
- **Evidence:** `deductions/v1/getGarnishmentDetails` returns HTTP 403 ("this user session is not
  authorized for the method specified") for every employee.
- **Decision:** garnishments come from deduction codes of type `G` and from voucher deduction lines.
  Docket, payee and limit details are a known gap. The fetch stops asking after the first refusal (one
  request on the full fetch), so only that employee carries a `SOURCE_UNAVAILABLE` warning (A-70). For
  every employee, `checkForGarnishments` says whether there are garnishments to miss: 3 live employees
  have some, and carry `GARNISHMENTS_NOT_READ` (A-83).

### A-83 PrismHR: whether an employee has garnishments
- **Issue:** garnishment details are refused (A-08), so an employee without garnishment elections might
  still have garnishments.
- **Evidence:** `employee/v1/checkForGarnishments` returns `enrolled` and `active`: "whether an employee has
  enrolled for garnishments" and "has active garnishments". It answers for the demo user. Live, both are
  true for 3 of the 194 employees: they have garnishments the output can't show.
- **Decision:** it is fetched for every employee. When either is true and no garnishment details came
  back, the employee gets a `GARNISHMENTS_NOT_READ` warning. The two answers are kept as sent.
- **Why:** A-70 again. For 191 employees, "no garnishments" is the provider's own answer, not an
  absence of data; the 3 that have some say so, instead of seeming to have none.

### A-10 isolved's payroll list and "corestream" deduction endpoints are refused
- **Evidence:** these return 401 "Authorization has been denied for this request", even right after a
  fresh sign-in: `/employees/{e}/payroll`, `/api/corestream/.../employees/{e}/deductions` and
  `/api/corestream/.../paygroups/{pg}/payrolls/{id}`.
- **Decision:** deduction setup comes from `/employees/{e}/payItems` (7 elected deduction items live, A-49), and
  payroll deductions come from check details. Each refused request is still reported on the employee or
  company it was for (A-70).
- **Why:** the alternative endpoints are documented and readable, so nothing is lost.

### A-17 PrismHR loan dates are YYYY-MM-DD, not the documented YYYY-DD-MM
- **Evidence:** PrismHR `#/components/schemas/EmployeeLoanDetails/properties/startDate` (and the related
  loan fields) say "YYYY-DD-MM". Live payment dates include `2014-10-17`, which is impossible as YYYY-DD-MM
  (there is no month 17), and every payment date falls on a Friday.
- **Decision:** parse them as YYYY-MM-DD, with a diagnostic if a value is ambiguous and conflicts.

### A-87 PrismHR retirement loans
- **Issue:** PrismHR files `benefits/v1/getRetirementLoans` under benefits, a topic outside the five data
  types (A-74), but a loan against a retirement plan is repaid by payroll deduction, which is deduction
  setup.
- **Evidence:** `#/components/schemas/RetirementLoan` documents each loan: `paymentAmount`, "amount
  employee will pay back per pay period"; `paybackAmount`, which "can include principal and interest";
  `amtPaidBackToDate`; `deductionStarts`, "date on which the deduction begins"; and `planId401k`, the plan
  the loan was taken against. Asked live for the 25 clients on 2026-10-15: 3 loans, all in client 102,
  each against plan "401k", and none of their employees among those fetched (A-07).
- **Decision:** fetched once per client, and each loan is a deduction election of category
  `RETIREMENT_LOAN`: a fixed amount per pay period, starting on `deductionStarts`, with the loan's
  details (amount, payback amount, paid to date, loan date) and the plan as `benefit_plan_id`. The
  response names no deduction code, so `code` is empty. `interestRate` has no documented unit and stays
  as sent, as do the override payment fields and the TPA loan ID.
- **Why:** the brief asks for deduction setup, and these are deductions with documented amounts and
  dates.

### A-91 PrismHR retirement plans, flex plans and benefit adjustments
- **Issue:** PrismHR files three endpoints of per-employee deduction setup under "benefits", a topic outside
  the five data types; the endpoint inventory's content check flags them (A-74).
- **Evidence:**
  - `getRetirementPlan` ("Get active retirement plans for an employee"): the employee's 401(k) elections
    and rules: pre-tax, Roth and catch-up percents and amounts, extra amounts, matching, escalation and
    deferral-limit overrides. Live sends `planDetail` where the spec documents `planDetails`.
  - `getFlexPlans`: FSA elections, deduction amounts and their start and stop dates.
  - `getBenefitAdjustments`: "amount to deduct from the employee's paycheck per cycle", over a number of
    future cycles, with what has been billed so far.
  - Asked live for all 194 fetched employees on 2026-10-16: a retirement plan for 119 (115 active, all
    "401k"), a flex plan for 1, and 2,464 benefit adjustments for 77 (342 with an employee amount). The
    others answer 404 "Retirement plans for employee ... does not exist." and "No benefit adjustments
    found ...", which count as empty answers (A-70).
  - All 115 employees with an active plan already have their 401(k) election from `getDeductions`, and
    the 19 plans with an elective percent match the 19 percent elections there. The plan adds rules
    around those elections, such as 14 catch-up percents.
- **Decision:** the three are fetched for every employee and kept as sent with the employee, in
  `provider_extensions`, like scheduled payments (A-80). They aren't mapped into elections: the elections
  payroll applies already come from the deduction endpoints, and folding plan rules and billing
  adjustments into them would mean reconciling two sources the provider keeps apart.
- **Why:** nothing about them is lost, and the deduction setup that drives paychecks stays one record per
  election.

### A-88 isolved garnishment limits
- **Evidence:** `EmployeeGarnishmentModel` documents `limit` as "Limit", `maximumAmount` as "Maximum
  Amount", `maximumPercent` as "Maximum Percent" and `ytdLimit` as "Year to Date Limit". Live, the 3
  garnishments have no nonzero `limit`, `maximumAmount` or `ytdLimit`, and 2 have a `maximumPercent`.
- **Decision:** a nonzero `maximumAmount` is the election's maximum, with no basis, since none is stated.
  `limit` stays as sent: it could be per check, per year or in total. The others stay as sent too, and a
  0 is no limit (A-73). A `percentageOf` outside its four documented bases stays as sent too, with a
  warning.

## Payroll runs and paychecks

### A-54 Gross pay and gross wages mean the same thing for every provider
- **Issue:** the providers' headline gross figures differ. PrismHR's `totalEarnings` includes non-cash pay
  (A-32). isolved reports both `grossWages`, which includes group-term life, and `grossPay`, which doesn't
  (A-28). UKG reports neither (A-58). Mapping each headline figure to one field would make that field mean
  different things.
- **Decision:**
  - `gross_wages` is every earning counted in gross, non-cash ones included: PrismHR `totalEarnings`,
    isolved `grossWages`, the sum of UKG's lines.
  - `gross_pay` is the part actually paid: gross wages minus non-cash earnings (`NON_CASH_FRINGE`,
    `REPORTED_TIPS`, and `MEMO` lines counted in gross). isolved `grossPay` is exactly that. For PrismHR
    and UKG it is derived, flagged `derived` with its formula, and only when every counted line has a
    known kind; otherwise it is null with a `GROSS_PAY_NOT_DERIVED` info diagnostic.
  - Each earning line's `in_gross` says whether the provider counts it in gross wages.
  - Every paycheck is checked, and the results are reported, never adjusted:
    - gross wages = sum of the lines counted in gross;
    - gross wages − non-cash earnings = gross pay, when both are provided;
    - gross pay − employee taxes − deductions = net;
    - payments = net.

    A check an unknown value blocks is reported as not applicable (A-73); a derived total is never checked
    against the lines it came from.
- **Result on the full fetch:** PrismHR 6,804 of 6,807 checks pass (the 3 failures are the two vouchers in
  A-32), isolved 543 of 543, UKG 61 of 61.

### A-32 PrismHR gross and net reconcile from the line items
- **Evidence:** on the 420 vouchers of the first sample:
  - `totalEarnings = sum(earning[].payAmount) + sum(otherEarningsDetail[].otherEarnAmount)` on **420 of
    420**.
  - The summary fields are the unreliable part: `otherEarnAmount` leaves out "Fringe" lines on 64
    vouchers, and `earnAmount` differs from its lines on 23.
  - Net pay reconciles on **420 of 420** once non-cash pay is excluded:
    `gross − non-cash earnings − employee taxes − deductions = netPay`. Non-cash means pay classes F
    (non-cash fringe), M (memo) and RT (reported tips), documented in
    `#/components/schemas/ClientCodes-PayCode/properties/payClass`. Such pay is taxed (it sits inside
    federal taxable wages) but not paid out.
- **Decision:** `totalEarnings` is gross *wages*, since it includes the non-cash classes. Gross pay is
  derived as `totalEarnings` minus the non-cash lines (A-54). Earning lines come from both lists (A-42),
  and their kind comes from `payClass` (or the client pay-code table for "other" lines). `earnAmount` and
  `otherEarnAmount` are kept in `provider_extensions`, not used.
- **On the full fetch (2,403 vouchers):** 6,804 of 6,807 checks pass. Two vouchers break the pattern, and
  their checks report it as `RECONCILIATION_MISMATCH`; nothing is adjusted:
  - one has a memo line of 250 while `totalEarnings` is 0, so here a memo line sits *outside* the total;
  - one is a negative (reversal) voucher whose net differs by 55.81 from its lines.

  So the rule holds widely but isn't universal, and the checks are what show where it doesn't.

### A-28 isolved check buckets and its two gross figures
- **Evidence:** for each check, the spec gives `check*`, `current*`, `ptd`, `mtd`, `qtd`, `ytd` and `ftd`
  amounts without explaining them. On all 15 check details of the first sample:
  - `checkDollars` equals `currentDollars` on every line;
  - `grossWages` equals the sum of non-memo earnings;
  - `grossPay` − employee taxes − deductions − garnishments = `netPay`;
  - `checkAmount + directDepositAmount = netPay` (also on all 430 rows of the check list).

  `grossPay` is a little below `grossWages` (by $0.37 to $9.92). The gap is exactly the check's group-term
  life lines on **15 of 15**: earnings whose client pay item has system benefit type "Group Term Life".
  isolved's own system earning describes that item as "Group Term Life - taxable amount over $50K":
  imputed income that is taxed but never paid. All 420 listed checks with a gap have `grossPay` below
  `grossWages`; the other 10 have none.
- **Decision:** `check*` is "this paycheck". `gross_wages = grossWages` and `gross_pay = grossPay`, which
  match the canonical meanings exactly (A-54).

### A-58 UKG pay statement line types, and "Fringe" payments
- **Evidence:**
  - UKG pay statements give no gross or net. Each line has a `type_name` in the form
    "<kind> (<modifiers>)". Live earnings show "Earning", "Earning (Auto)", "Earning (Auto Reduce)",
    "Earning (Fringe, Auto)" (code "GTL-Imp Inc") and "Reimbursement(Neg Ded, Auto)". The docs sample shows
    "Deduction (Manual)".
  - Payments are "Check", "Direct Deposit" and "Fringe".
  - On every live statement (22 of 22 in the first sample, 61 of 61 in the second UKG fetch), each
    "Fringe" payment equals the fringe earnings, and
    `sum of earnings − fringe earnings − employee taxes − deductions = check + direct deposit`.
- **Decision:**
  - "Earning" lines are `EARNINGS`, "Reimbursement" lines `REIMBURSEMENT`, and lines with the "Fringe"
    modifier `NON_CASH_FRINGE`.
  - A modifier outside those seen (Auto, Auto Reduce, Manual, Fringe, Neg Ded) leaves the line `UNMAPPED`
    with a warning, since it could change the meaning.
  - "Fringe" payment rows aren't payments: nothing is paid. They stay in `provider_extensions`.
  - Gross wages are derived as the sum of the lines, gross pay by subtracting the fringe lines (A-54), and
    net pay from the check and direct-deposit payments. A payment of unknown type blocks the derived net
    (A-64).
  - Lines with no amount carry no money for the statement, so they don't become lines; they stay in
    `provider_extensions`.
  - Each tax line becomes one employee line and one employer line, each with its own subject wages.
    Deduction `er_amount` becomes an employer contribution.

### A-51 isolved check list vs check detail, and year-to-date-only lines
- **Evidence:**
  - The legal-level check list (`/legals/{l}/checks`, 430 live rows) is a summary. Its line-item arrays
    are empty on all 430 rows, and `checkTypeDescription` is null on all 430.
  - For the 15 checks of the first sample also fetched in detail, `checkSequence` is 1 in the list and 0
    in the detail on all 15. `employeeName` differs on one check, and address fields on a few others.
  - Detail arrays also hold lines with no `check*` value at all: 52 of 121 earning lines and 26 of 137 tax
    lines in the first sample. They carry only month-, quarter- or year-to-date amounts from earlier
    checks.
- **Decision:**
  - The detail is used whenever it was fetched.
  - A list-only check becomes a pay statement with its header and totals, and no lines. Its type is
    `UNMAPPED` (missing, so no warning), it gets a `DETAIL_NOT_FETCHED` info diagnostic and
    `lines_fetched: false`, so its empty line lists read as unknown, and the line-based checks are skipped.
  - The list has no deposit lines (`directDeposits` is null on all 430 rows), so its
    `directDepositAmount` becomes one direct-deposit payment without an account, and `payments = net` can
    still be checked.
  - Checks link to employees by `employeeId` only, never by name.
  - Only lines with a `check*` value are this paycheck's lines. The others stay in `provider_extensions`.
- **Why:** the list omits fields rather than contradicting them. The name and address are snapshots, kept
  raw in `provider_extensions`.

### A-42 PrismHR "other earnings" lines belong in the paycheck
- **Evidence:** `PayrollVoucher` has `earning[]` and `otherEarningsDetail[]`. `totalEarnings` equals
  `earnAmount + otherEarnAmount` on only 333 of the 420 vouchers in the first sample (A-32).
- **Decision:** both lists become earning lines; otherwise gross can't reconcile.

### A-18 PrismHR earning `payAmount` is the line total
- **Evidence:** PrismHR `#/components/schemas/Earning/properties/payAmount` says "pay per hour or unit",
  and `unitRate` is undocumented. Live, `hoursUnits × unitRate = payAmount` on **465 of 465** lines.
- **Decision:** the line amount is `payAmount` and the rate is `unitRate`.

### A-38 PrismHR earning quantity is hours *or* units
- **Evidence:** `#/components/schemas/Earning/properties/hoursUnits` is "hours or units paid", and
  `hoursWorked` is a separate field. The pay code's `payReason`
  (`#/components/schemas/ClientCodes-PayCode/properties/payReason`) is documented as "hours (H) or units
  (U)".
- **Decision:** each earning line has a `quantity` with a unit (`HOURS`/`UNITS`/`UNKNOWN`), taken from the
  pay code's `payReason` via the client code table, plus a separate `hours_worked`. If the pay code isn't
  in the table, the unit is `UNKNOWN`.

### A-24 UKG pay-statement hours are milliseconds
- **Evidence:**
  - UKG `#/schemas/364` types earnings `hours` as an integer with no unit. Live, all 23 earning lines in
    the first sample that have both hours and a rate satisfy `(hours ÷ 3,600,000) × base_rate =
    ee_amount`, and none satisfies `hours × base_rate`. Milliseconds are also documented elsewhere in the
    same API (compensation `time`, pay-info `standard_work_day`).
  - In the second UKG fetch, 67 of 71 such lines satisfy it. The other 4 are all overtime (code "OT"),
    where `ee_amount = 1.5 × hours × base_rate`. So `base_rate` is the employee's base hourly rate, and
    premium lines multiply it.
- **Decision:**
  - Hours are converted, with the raw value kept and the formula recorded.
  - `base_rate` becomes the line's `rate` only where hours × base_rate = amount on that line. Otherwise it
    stays raw in `provider_extensions`, with a `BASE_RATE_NOT_LINE_RATE` info diagnostic giving the
    multiple, because a canonical rate must multiply out to the amount.

### A-53 isolved earning kinds come from the system earning each pay item is built on
- **Evidence:**
  - A check's earning line has only `isMemoEarning` to say what kind of pay it is. Its client pay item
    (linked by title, A-49) names the system earning it is built on (`systemPayItemType`), and
    `/api/system/earnings` describes each system earning in isolved's own words:
    - "Regular": "Earnings paid based on the employee hourly rate or per pay Salary";
    - "Vacation", "Sick" and "Holiday": "Earnings paid based on hours input times the employee normal
      hourly rate";
    - "Bonus": "Earnings paid based on hours or dollar input"; "Commission": "Earnings paid based on
      dollar input only";
    - "Overtime @ Flat 1.5": "Overtime paid at 1.5 ee hourly rate"; "Overtime - Blended Rate": "Blended
      rate used to pay OT hours";
    - "Other Hrs or Dollars": "… Fully taxable. Paid.";
    - "Misc Non Taxable": "Non-taxable earning. Paid to ee. … reimbursement earning.";
    - Group Term Life items: "Group Term Life - taxable amount over $50K" (and, for one variant, "Not
      Paid").
  - "ShiftDiff" is described only as "Shift Diff", but live it sits inside `grossPay` on both checks where
    it appears, so it is paid.
- **Decision:**
  - Memo lines are `MEMO`, from the flag. A line without the flag gets `FLAG_MISSING` (A-73).
  - Otherwise, system benefit type "Group Term Life" is `NON_CASH_FRINGE`, "Misc Non Taxable" is
    `REIMBURSEMENT`, and the paid earnings above are `EARNINGS` (`EARNING_CLASS` in
    `providers/isolved/codes.py`).
  - Any other system earning, for example "1099M Non EE Comp", stays `UNMAPPED` with an `UNMAPPED_CODE`
    warning: its description doesn't say whether it is paid.
  - The kind keeps the system benefit type and pay item type as its raw value.
- **Why:** these are isolved's own definitions, not the customer's titles. All 42 non-memo earning lines
  on the 15 detailed checks of the first sample get a kind this way.

### A-67 Earning categories: what a line pays for, from the provider's own classification
- **Issue:** an earning line's kind (A-32, A-53, A-58) says how it is paid: cash, reimbursement, non-cash.
  It doesn't say what it pays for, so overtime or vacation pay can't be compared across providers. The
  codes themselves are the customer's (`REG`, `OT`, `Holiday`), and their names are not evidence.
- **Evidence:**
  - **PrismHR:** each pay code carries `talxPayType`, "download code used for employment verification",
    documented with its values (PrismHR
    `#/components/schemas/GetPaycodeDetailsResponse.PayCode/properties/talxPayType`): R Regular,
    V Vacation, S Sick, B Bonus, E Severance, H Holiday, P Pension, W Wages, O Overtime, C Commissions,
    T Tips, M Miscellaneous, K Workers' Compensation. `getClientCodes` sends the same field. Live, it is
    blank on every pay code of all 25 clients.
    - `rateClass` is documented as 'S' (Straight), 'P' (Premium), 'D' (Doubletime), 'O' (Other). Live,
      both "Overtime" (`OT`) and "Half Time" (`HALF`) are Premium, and another "Overtime" code (`O/T1`) is
      Straight.
    - `payType` R/V/S is documented as Regular, Vacation, Supplemental. Live, code `Sick2` has `payType`
      V, so payType reads as a withholding class, not a category.
  - **isolved:** each client pay item names the system earning it is built on (A-53), and
    `/api/system/earnings` describes each one: "Overtime @ Flat 1.5" is "Overtime paid at 1.5 ee hourly
    rate"; "Overtime - Blended Rate" is "Blended rate used to pay OT hours"; "1099M Non EE Comp" is "Used
    to enter 1099M non employee compensation (box 7)". Live, the Vacation, Sick and Holiday items all sit
    under system benefit type "Leave Accrual".
  - **UKG Ready:** `lookup/earning-codes` lists only name, code and ID. Nothing classifies a code.
- **Decision:** `EarningLine.category`: `REGULAR` `OVERTIME` `DOUBLE_TIME` `SHIFT_DIFFERENTIAL`
  `VACATION` `SICK` `HOLIDAY` `PAID_TIME_OFF` `BONUS` `COMMISSION` `TIPS` `SEVERANCE` `PENSION`
  `WORKERS_COMPENSATION` `NON_EMPLOYEE_COMPENSATION` `OTHER`.
  - It is set on lines of kind `EARNINGS`, or of unknown kind. Reimbursement, fringe, tips and memo lines
    are already specific, so their category is null.
  - **PrismHR:** from `talxPayType` (`TALX_PAY_TYPE`); Wages and Miscellaneous are `OTHER`. Rate class
    'D' gives `DOUBLE_TIME` when the TALX type is blank or Overtime. Premium and Straight set nothing.
  - **isolved:** from the system earning (`EARNING_CATEGORY`); a "Leave Accrual" item whose system
    earning isn't listed is `PAID_TIME_OFF`. An unknown system earning is `UNMAPPED` with a warning: it is
    a provider value.
  - **Otherwise** the category is `UNMAPPED`, with the earning code as raw value and its name as label
    (`clientCodes.payCode[].id`, `earnings[].earning.code`). As with other customer codes (A-35), there is
    no warning on each paycheck: it is one decision per code, made in a mapping file (A-65).
- **Result on the full fetch:**
  - isolved: every earnings line gets a category: Regular 40, Holiday 19, Overtime 10, Vacation 5, Shift
    differential 3, Sick 1.
  - PrismHR (TALX blank) and UKG come to 9 and 6 review decisions. The name hints for them are good (`REG`
    like REGULAR 1.00, `OT` like OVERTIME 1.00) but stay hints.
- **Why:** PrismHR's TALX type and isolved's system earnings are each provider's own classification, set
  by the provider or the PEO, not the customer's naming. A PrismHR tenant that fills in `talxPayType` gets
  categories with no further work.

### A-68 Tax types: the provider's own codes and descriptions, checked against statutory rates
- **Issue:** without a canonical type, a tax line is just the provider's code and label, and Social
  Security withheld can't be summed across providers.
- **Evidence:**
  - **PrismHR:** the spec documents the voucher tax code only as "tax deduction code", but every line
    carries PrismHR's own description, identical across all 25 live clients.
    - Federal codes: 00-10 "Federal Income Tax", 00-11 "Medicare - Employee", 00-12 "Soc Security -
      Employee", 00-15 "Medicare - Employer", 00-16 "Soc Security - Employer", 00-17 "Fed Unemployment".
      The arithmetic agrees: 00-12 takes exactly 6.2% of taxable wages on 2,263 of 2,273 lines and 00-11
      1.45% on 2,254. The employer lines carry `comTaxRate` 0.062, 0.0145 and 0.006.
    - State codes are `<2-digit state>-<2-digit tax>`. Some tax numbers mean the same thing in every state
      they appear in:
      - `20` "<ST> Income Tax": 35 of 35 states;
      - `24` "<ST> Unemployment": 40 of 40;
      - `21` disability: 4 of 4; `25` employer disability: 3 of 3;
      - `22` employee unemployment: 3 of 3; `40` paid family and medical leave: 5 of 5.

      Others mix meanings. For example, `41` is paid family leave in MA, OR and WA, but "BOND" in CO and
      "NV PAYROLL EXCISE TAX" in NV. `26` and `28` are assorted state assessments, some with no
      description.
    - Local codes are `<5- or 9-digit locality>-<2-digit tax>`. Tax number `31` reads "<city>, <ST> CIWT"
      (city income withholding tax) in 22 of 22 localities, and `39` is a resident CIWT.
  - **isolved:** `itemCode` is null live. The description is the system tax's: the spec defines a legal's
    taxes as system taxes, with "taxDescription: Description of the system tax". Federal lines read
    "FEDERAL WH", "SOC SEC EE/ER", "MED EE/ER" and "FUTA ER". SOC SEC is exactly 6.2% and MED 1.45% of
    taxable wages on all 40 detailed checks. State lines read "<state> WH", "<state> SUI ER/EE" or
    "<state> SDI EE", with the state as a USPS code or full name ("PA WH", "CALIFORNIA WH").
  - **UKG Ready:** `lookup/tax-codes` is "the list of supported tax codes". Its documented sample gives
    FIT "Federal Income Tax", FUTA "Federal Unemployment Tax", FICA "OASDI", MEDI "Medicare" and
    "Additional Medicare".
    - Live, the codes "Social Security" and "Medicare" also appear, at exactly 6.2% and 1.45%, as do FICA
      and MEDI.
    - State codes read `<tax>:<state>[:<n>]`. `SUTA:WI:2` is named "ER SUTA Wisconsin" and has employer
      amounts only.
    - `SIT:WI` is named just "Wisconsin". Its subject wage equals FIT's on 62 of 63 live statements,
      including all 28 where FIT's differs from Social Security's, so it is taxed on the income-tax wage
      base.
- **Decision:** `TaxLine.type`: `FEDERAL_INCOME` `SOCIAL_SECURITY` `MEDICARE` `ADDITIONAL_MEDICARE`
  `FEDERAL_UNEMPLOYMENT` `STATE_INCOME` `STATE_UNEMPLOYMENT` `STATE_DISABILITY` `STATE_PAID_LEAVE`
  `LOCAL_INCOME` `OTHER`. `TaxLine.state` holds the USPS code of a state-level tax.
  - Mapped exactly: the federal codes above. Mapped by structure: only the PrismHR tax numbers listed, the
    isolved "<state> <tax>" forms, and UKG `SIT:`/`SUTA:`.
  - A state must be a real one from the USPS list ("KANSAS CITY WH" is not a state tax). It comes from the
    code (UKG), the description (isolved), or the start of the description (PrismHR: "WI Income Tax",
    "ALASKA SUTA EE").
  - Anything else is `UNMAPPED` with an `UNMAPPED_CODE` warning, because tax codes are the provider's, not
    the customer's. `review` lists each code once and, where every line is taxed at exactly 6.2%, 1.45% or
    0.9%, suggests that tax (A-66).
  - A mapping file can set the type, but not the state.
- **Result on the full fetch:**
  - PrismHR: 18,020 of 18,891 tax lines are typed. The other 871 are 51 codes, mostly state assessments
    and local non-income taxes; each line carries a warning, and `review` lists each code once.
  - isolved: 262 of 304 typed. Three local taxes and Oregon's workers' benefit fund (employee and
    employer) are not.
  - UKG: 362 of 370 typed. Three Minnesota codes are not.
  - Every state-level line has its state.
- **Why:** each rule rests on the provider's own code and description, and the federal ones on exact
  statutory arithmetic as well. A tax number that means different things in different states stays
  unmapped rather than being right most of the time.

### A-40 Record links and paycheck-to-run joins
- **Evidence:** isolved checks carry `payrollRunNumber`, while run history has both `id` and `runNumber`
  (`#/definitions/AOS.PayrollOffice.RestAPI.Models.PayrollRunHistoryModel`). PrismHR batch lists carry
  periods per pay group (`#/components/schemas/BatchByDateResponse-BatchList-PayGroup`).
- **Decision:** every record carries explicit relationship keys (model §2.1). An isolved check joins its
  run on legal company + pay date + run number, never by treating the run number as a run ID; the run
  keeps its run number among its source IDs. An ambiguous
  or missing match leaves `payroll_run_id` null, with a diagnostic. A record that points at another one
  missing from the bundle says so (`EMPLOYEE_NOT_IN_BUNDLE`, `RUN_NOT_IN_BUNDLE`, A-72). Payroll runs keep
  periods per pay group.

### A-21 PrismHR batch codes that the spec doesn't document
- **Evidence:** PrismHR `#/components/schemas/BatchList/properties/batchType` documents R/M/S/V. Live, an
  empty `batchType` also appears, and the `batchStatus` values (`COMP`, `TS.READY`, `TS.ENTRY`,
  `INITFAIL`, and on the full fetch also `INITCOMP`, `TSOKAUTO`, `TSOKCOMP`) have no documented meanings.
- **Decision:**
  - An empty batch type maps to `UNMAPPED`.
  - `COMP` maps to `COMPLETED`, because every voucher in a `COMP` batch has status `PRNT` (printed).
  - Other statuses stay `UNMAPPED`, with the raw value kept.

### A-57 UKG payroll and pay statement types and statuses
- **Evidence:**
  - `lookup/payroll-types` is documented as "the list of supported payroll types". The documented sample
    and the live tenant list the same names (Regular, Void, Correction, Historical and others) under
    different IDs.
  - `lookup/pay-statement-types` is documented the same way, but the live tenant also has names like
    "Comm" and "Regular 2", which a customer must have added.
  - Payroll `status` (`#/schemas/360`) lists values without definitions. The documented actions run OPEN →
    close → CLOSED → finalize ("Performs the finalize process on the specified payrolls if closed") →
    FINALIZED.
- **Decision:**
  - Payroll types map by name, never by ID: Regular, Void, Correction and Historical.
  - Pay statement types map only for the documented sample names Regular, Manual and Historical.
  - Payroll statuses: OPEN, CLOSED and SUBMITTED map to themselves and FINALIZED to `COMPLETED`, each
    being a state a documented action requires or produces ("Performs the submit process on the
    specified payrolls if closed"). NEW and the four `*_FAILED` values stay `UNMAPPED`: nothing defines
    them, and a name is not a definition (A-26).
  - Anything not finalized gets a `NOT_FINALIZED` diagnostic (A-13).

### A-13 UKG payroll runs are all open
- **Evidence:** all 89 payrolls (2025-09-12 to 2027-06-04) and all 63 pay statements on the full fetch
  have status `OPEN`.
- **Decision:** normalize them, with a `NOT_FINALIZED` diagnostic saying the amounts may still change.

### A-11 isolved has only historical, imported payroll
- **Evidence:**
  - Pay group 7612 has 231 runs: 36 are "Completed Payroll Run" (all "Data Conversion", 2018) and 195 are
    "Payroll Not Processed".
  - The other pay groups have no run history (a documented 404, A-70).
  - The legal-level check list returns 430 checks, all from "Data Conversion" runs. The ones fetched in
    detail are all type "Adjustment".
- **Decision:** normalize these as they are, with run type `HISTORICAL_IMPORT`. Synthetic fixtures cover
  regular runs.

## Where live data differs from the specs

### A-90 PrismHR payroll schedule: the code and its description are swapped
- **Evidence:** `#/components/schemas/ClientPayrollSchedule` documents `payPeriod` as a "pay period number"
  and puts the codes on `payPeriodDesc`: "'D' (Daily), 'W' (Weekly), 'B' (Biweekly), 'S'
  (Semi-monthly), 'M' (Monthly), ...". Live, `payPeriod` holds the code and `payPeriodDesc` the description.
- **Decision:** follow the live data: `payPeriod` is read as the code, through the documented list, and
  `payPeriodDesc` is its label. This list is also the evidence for what the employee's pay period codes
  mean, so the swap matters beyond the schedule itself.

### A-16 PrismHR response keys differ from the spec
- **Evidence:**
  - Live `getPayrollVoucherForBatch` returns `payrollVoucher`; PrismHR
    `#/components/schemas/PayrollResponseWithPagination/properties/payrollVouchers` documents
    `payrollVouchers`.
  - Live `getPayrollSchedule` returns `clientPayrollSchedule`; the spec documents `clientPayrollSchedules`.
- **Decision:** the converters accept both spellings, and the fixtures include both.

### A-78 More PrismHR keys that differ from the spec, among them the employee's employer
- **Evidence:** live PrismHR sends `person.employerId` where `#/components/schemas/Person/properties/employerIds`
  documents `employerIds`, "employer(s) for which the employee works". All 194 employees carry one live,
  and reading only the documented key would find none. `getEmployersInfo` returns the same employer for
  all 35 employees asked. `getHistory` returns `historyRecord` (documented `historyRecords`) and
  `getAllPrismClientContacts` returns `prismClientContact` (documented `prismClientContacts`).
- **Decision:** as in A-16: the converters read both spellings, and the fixtures include both. The fixture
  validator translates aliases per endpoint and at any depth (A-43).
- **Why:** a field sent under one name and documented under another loses nothing when kept, but
  normalizes nothing either, so it needs the same care as a renamed list.

### A-22 PrismHR voucher fields the spec doesn't document
- **Evidence:** the live vouchers have `isManualCheck` and `hsaPeoMatch`, which are not in the
  `PayrollVoucher` schema.
- **Decision:** keep both in `provider_extensions`.

### A-47 Live PrismHR responses don't match their own schema, in three ways
- **Evidence:** of the 428 live 200 responses in the first sample, 422 validate against the spec once
  `null` is allowed in typed fields. The remaining six show:
  - `extension` is `null` where an object is declared;
  - every employee lacks the "required" `client.hawaiiMedWaivers`;
  - `clientMaster.regRebuild[].regRebuildDate` arrives as epoch milliseconds (e.g. `1550080171000`) where
    a string is declared.
- **Decision:**
  - Converters accept null or missing for every field. `regRebuildDate` is not mapped, so it stays raw in
    `provider_extensions`.
  - The fixture generator fills every required property the scenario doesn't set with `null`, as live
    data does. Fixture validation allows `null` and nothing else (`fixtures/validate.py`).
- **Why:** the fixtures should look like what PrismHR actually sends, while staying checkable against the
  published contract.

### A-52 Live isolved employee records don't match their own schema, in two ways
- **Evidence:**
  - `EmployeeModel.maritalStatus` is "Marital status code" with `maxLength` 1, but live sends the
    description: "Single" (9), "Married" (10) or null (11). `/api/lookup/maritalStatuses` maps each code
    to its description. `gender` and `citizenship` are documented as descriptions and arrive as
    descriptions.
  - `idType` is required but absent from all 30 employee records and from every employee-list row.
  - Of the 210 live 200 responses in the first sample, 177 validate against the spec once `null` is
    allowed. The other 33 (30 employee details and 3 employee-list pages) all lack `idType`, and 22 of
    them also send a marital status longer than one character.
- **Decision:**
  - Marital status, gender and citizenship map by their lookup description. A code (the documented form)
    is first translated through the lookup, and `raw` keeps exactly what was sent.
  - The fixtures send both forms.
  - Fixture validation ignores exactly one deviation, `maxLength` on `maritalStatus` (`DEVIATIONS` in
    `fixtures/validate.py`). The generator fills `idType` with null, like other unset required fields
    (A-47).
- **Why:** as in A-47, fixtures should look like live data while staying checkable against the published
  contract.

### A-61 Live UKG responses don't match their own schema, in five ways
- **Evidence:** of the 112 live 200 responses in the first sample, 78 validate once `null` is allowed.
  The rest show:
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

## Unknown values: review and mapping files

### A-65 Unknown values are resolved by mapping files with evidence, not by code changes
- **Issue:** every tenant brings codes no code table knows, such as PrismHR citizenship `Y` and new batch
  statuses. They come out `UNMAPPED` with a warning, but resolving one shouldn't take a code change, and
  the warnings are spread over thousands of records.
- **Decision:**
  - `python -m normalization review` collects every still-unmapped value into distinct decisions:
    provider, tenant, field, raw value, label, record count, the companies it appears in, and examples.
    Array positions in a field don't count as different fields. On the final fetch, 7,995 record mentions
    come down to 151 decisions, with the reviewed mapping files applied (A-86). It also writes a
    mapping-file template per tenant.
  - A mapping file (`--mappings`) resolves values as data, for one tenant (A-69):
    - It fills only values that would otherwise be `UNMAPPED`, and never overrides a code table built from
      documentation.
    - Every entry needs written evidence, and the value must be valid for the field's canonical enum. An
      entry missing a part stops loading with a clear error; a value the enum doesn't have stops the run
      when a record reaches that rule.
    - It applies during conversion, so everything downstream uses the resolved value: derived gross pay
      and the checks, for example.
    - Each record it touched gets a `MAPPED_BY_FILE` note quoting the evidence, in place of its
      `UNMAPPED_CODE` warning.
- **Why:** the evidence rule stays the same, but the person with the evidence (a tenant admin, an analyst
  reading the provider's setup) can apply it without a release, and every use is traceable.

### A-69 Mapping files belong to one tenant, and a rule can be limited to companies
- **Issue:** a customer's codes are configured per company. In the live PrismHR bundle, pay code
  `BONUSup` is "Bonus" in most clients and "Extra Bonus" in another, and `MEMO` is "Memo" in most and "Xmas
  Club CF" in one. A rule keyed only by provider, field and raw value would apply to every company, and to
  any tenant if the file were reused. Mapping files are also how PrismHR and UKG earning codes get their
  category (A-67).
- **Decision:**
  - A mapping file must name its `tenant`. A file for another tenant or provider is skipped, and the
    output says so.
  - A rule may list `companies`, by canonical company ID. It then applies only to records of those
    companies; without the list, it covers the whole tenant.
  - Two rules for the same value may disagree only if their companies don't overlap; otherwise loading
    stops with an error.
  - The converters convert one company at a time inside a scope, so a rule applies during conversion
    (A-65) and never to another company's records.
  - The `review` template lists, for each row, the companies the value was seen in, so the default is
    narrow. Widening a rule to the whole tenant means deleting its list, a deliberate act.
  - The output lists each mapping file used, with its SHA-256 and every rule that matched nothing (A-71).
    A mistyped company ID shows up there instead of silently doing nothing.
- **Why:** this follows Finch, whose custom rules apply to one customer connection. Evidence about one
  company's code says nothing about another company's code that happens to share the name.

### A-66 Suggestions for unmapped values: arithmetic first, similar names as a hint, never applied
- **Issue:** the review queue (A-65) lists decisions, but each one starts from nothing. The project must
  run locally, and the evidence rule forbids mapping from names.
- **Decision:** `review` attaches suggestions that a person accepts or rejects; nothing is applied until a
  mapping file says so. Both methods are local, use the standard library only, and are deterministic.
  - **Arithmetic (evidence):**
    - For an earning line of unknown kind, each paycheck it appears on is tested: do the provider's own
      totals reconcile with the line paid in cash, or not paid out? The test uses `gross wages − non-cash −
      employee taxes − deductions = net`, plus `gross wages − non-cash = gross pay` where the provider
      reports gross pay. Paychecks with several unknown lines, or no net pay, are inconclusive. If every
      tested paycheck agrees, the suggestion is that class, with the paycheck count: cash gives
      `EARNINGS`/`REIMBURSEMENT`, non-cash gives `MEMO`/`NON_CASH_FRINGE`/`REPORTED_TIPS`. Arithmetic
      can't choose within a class, and disagreement is reported as contradictory, with no candidate.
    - For an unknown tax code (A-68), each line with money is tested against the fixed federal rates:
      Social Security 6.2%, Medicare 1.45%, Additional Medicare 0.9% (26 U.S.C. 3101 and 3111). If every
      line matches the same one, it is suggested, with the line count.
  - **Similar names (a hint, labeled "not evidence"):**
    - The unknown raw value and label are compared with texts already mapped to the same canonical type:
      every provider's code tables, values mapped in the reviewed output, and the canonical value names.
    - The score is the higher of an IDF-weighted word overlap and a character-trigram overlap. Up to three
      values scoring at least 0.3 are listed, and where arithmetic has narrowed the class, only values in
      it are ranked.
    - Open codes, with no canonical list, get no suggestion. Neither do texts without letters, such as the
      tax code `24-26`, which would otherwise match `26-24` on shared digits alone.
- **Results:**
  - On the synthetic scenarios, UKG "Earning (Memo)" reads as not paid out (1 of 1 paychecks), and MEMO
    ranks first by name. isolved "1099M Non EE Comp" reads as paid in cash. "Leave - FMLA" is like
    ON_LEAVE (0.44).
  - On the final fetch, 76 of the 151 decisions get a name hint. None gets an arithmetic suggestion,
    because no live earning kind or Social Security or Medicare code is unknown.
  - Values that resemble nothing known, such as `Y` and `TS.READY`, get nothing rather than a forced guess.
- **Why:** arithmetic on the provider's own totals is the strongest evidence available offline. Names
  speed a person up but must not decide. A local LLM could be added as a third suggester under the same
  rules: proposals only, data never leaving the machine.

### A-86 Codes documented only by name are confirmed by a person, in a reviewed mapping file
- **Issue:** UKG documents several enums as bare names, with no definition in its reference and no label
  in any response: deposit account types (CHECKING, SAVINGS), the deposit type RESERVE_LIVE_CHECK, gender
  and citizenship (A-79). The converters don't map names (A-26), so these come out `UNMAPPED`, though
  "CHECKING" plainly names a checking account. Mapping some plain names in code and not others would
  apply the rule unevenly.
- **Evidence for the approach:**
  - The brief: "undocumented meanings remain unknown ... Discover the mappings and define your own
    canonical enums", with an assumption documented wherever the data is unclear. The organizer's UKG
    lookup reference: "Per-code meanings are not inferred from enum labels."
  - Commercial payroll APIs map plain values into their own enums and keep the provider's value at hand:
    Merge treats such enums as open, passing a value it doesn't map through and returning the original on
    request. Finch leaves a field empty when it "can't infer a reasonable value".
- **Decision:**
  - The converters keep the rule: nothing is mapped from its name.
  - `mappings/` holds reviewed mapping files (A-65), one per tenant (A-69). Each rule is a person's
    decision that the name states the meaning, with the reason written next to it: the value is the
    canonical term word for word, names one of the four Form I-9 citizenship categories, or, for
    RESERVE_LIVE_CHECK, a "live check" is a paper paycheck and the documented row names no bank account.
  - The live demo tenant's file confirms CHECKING, SAVINGS, RESERVE_LIVE_CHECK, MALE, FEMALE, NON_BINARY
    and the four citizenship values. The synthetic tenant gets the same rules, so the demo shows them
    applied. Left out on purpose, because their names don't say enough: gender UNDEFINED, the deposit
    methods NET_PAY and DIRECT_DEPOSIT_PER_OF_REMAINDER, the rate periods WEEK and MONTH and the
    `*_FAILED` payroll statuses.
  - Every command applies the files in `mappings/` to their own tenants by default, and
    `--no-reviewed-mappings` shows the converters' output alone. Each record a rule resolved carries a
    `MAPPED_BY_FILE` note quoting the reason, and the output lists the files used, with their hashes and
    any rule that matched nothing (A-71).
- **Result:** on the live fetch, the file resolves 7 deposit account types, 24 genders and 12
  citizenships; 5 of its 10 rules match nothing there yet.
- **Why:** the evidence rule stays exact, and the call a person makes is recorded where it can be
  reviewed, changed or dropped, instead of being buried in a code table.

## Output, provenance and tests

### A-36 Output: JSON and SQLite
- **Decision:**
  - Every run writes `<record type>.json` (records sorted by ID), `summary.json`, `provenance.json` (A-71)
    and `canonical.sqlite` (`src/normalization/export.py`).
  - `summary.json` gives record counts, diagnostics by severity, check results, and request outcomes
    (A-70).
  - In SQLite the records are linked by canonical ID: company, then employee, then deposits, deductions
    and paychecks. Paycheck lines, reconciliation checks, diagnostics and sources have their own tables,
    as do employees' pay rates, contacts and organization units, and a `pay_statement_overview` view joins
    paychecks to employees and checks.
  - Every row also keeps the full canonical record as JSON in `record`, so nothing is lost.
  - Money stays exact TEXT, as in the JSON, because SQLite's REAL would round it.
  - Foreign keys are declared but not enforced, because a paycheck may name an employee whose record
    wasn't fetched (`EMPLOYEE_NOT_IN_BUNDLE`); `PRAGMA foreign_key_check` lists exactly those.
  - The canonical model is also exported as JSON Schema, one file per record type under `schemas/`, and
    tests check that every golden record validates against it.
- **Why:** JSON is easy to read and diff, and SQLite lets anyone query the linked records with plain SQL.

### A-71 Every output records what produced it
- **Issue:** a result that changes between two runs should be explainable. Data platforms record this
  lineage for the same reason.
- **Decision:** each output carries its provenance, in `provenance.json` beside `summary.json` and in the
  SQLite `sources` table:
  - the bundle: provider, tenant, folder name, save time, number of captures, and a SHA-256 over every
    file;
  - the `as_of` date the records were evaluated at (A-33);
  - the request outcomes (A-70);
  - each mapping file used, with its SHA-256 and any rule that matched nothing (A-69), and any file
    skipped;
  - the code: package version and, when run from a git checkout, the commit and whether the working tree
    had uncommitted changes.

  The commit and write time stay out of `summary.json`, which the golden files compare.
- **Why:** with the snapshot hash, the date, the mapping-file hashes and the commit, any output can be
  reproduced, or its difference from another explained.

### A-62 Every source field is mapped, kept or dropped for a stated reason
- **Method:** `python -m normalization coverage` runs the converters with tracing on and walks every saved
  response leaf by leaf, writing [docs/FIELD_COVERAGE.md](FIELD_COVERAGE.md) from the live fetches.
  Each field is mapped into a canonical record, kept in `provider_extensions`, dropped with a reason, a
  reference table read by code, or unused.
- **Two failures are checked, and the command and the tests fail on either:**
  - a field both mapped and kept, which means it was read after the leftovers were taken;
  - a field "lost": neither mapped nor kept, because the leftovers of its object were never collected
    (A-73), or because a converter marked it as handled elsewhere and nothing else took it.
- **Marked is not read.** A converter can mark a subtree it doesn't read, such as the deposit settings in
  PrismHR's employee response. A marked field counts as mapped or kept only where another reader maps or
  keeps it; otherwise it is dropped with the reason the mark gives (an echo of the employee's own ID, a
  copy of a value mapped elsewhere), or lost. Counting a marked field as mapped would hide a loss, such
  as PrismHR's shared deposit settings for an employee with no account; those are kept on each deposit
  record, or on the employee when there is no account. The property tests also put unknown fields inside
  nested objects, not only at the top level (A-72).
- **Read is not kept, either.** A converter can read a field and still lose its value, for example by
  building an address and then dropping it for lack of a street. So `tests/test_value_tracing.py` checks
  the outcome: it plants a unique marker in each field the report calls mapped or kept, normalizes, and
  requires the marker in the output. Fields where a marker rightly doesn't appear (an ID that repeats the
  request path, a list row its detail replaces) carry written reasons in the test. An address is kept
  when any part but the country is present; a country alone, which a provider may fill in by default, is
  left as sent.
- **A value sent under two keys** (UKG's `state_code` and `state`, a cost center's `display_name` and
  `name`, PrismHR's documented and live spellings of A-78) is mapped from the first one present. Another key
  with the same value is dropped as a copy, with that reason; one with a different value is kept in
  `provider_extensions`. Live, all 26 UKG addresses send the same state under both keys, and 85 of 422
  paycheck cost centers have a `name` different from their `display_name` (always part of it), so those
  names are kept.
- **A response nobody reads fails too.** The command also fails when an endpoint's response goes wholly
  unread, except a short list of lookups unread by design, each with its reason (`UNREAD_BY_DESIGN`).
- **What is kept where:** responses with no record of their own are kept with the record they describe:
  PrismHR active benefit plans and pay-rate history on the employee (there is no benefit plan record,
  model §7); isolved status, salary and alternate-rate history on the employee; the isolved client record
  on the company; the fields a PrismHR voluntary deduction adds to its election; and PrismHR scheduled
  payments and UKG tax setup, benefit plans and position assignments on the employee (A-80).
- **Converters read only the value they map,** so the other values in the same object stay in
  `provider_extensions`: an isolved deduction keeps every calculation parameter, and a check line with
  both hours and units keeps the units. Regression tests check that they survive.
- **What stays unread:** crawl indexes such as employee lists (each record is read from its own response),
  list rows whose detail was used instead, lookups the converters don't need, request echoes and paging
  envelopes.
- **Why:** preserving what the source data means includes not losing it, and the report makes every
  field's fate checkable.

### A-72 Rules that must hold for any input are tested on generated inputs
- **Issue:** example tests check the scenarios someone thought of. Whether the converters are fitted to
  those examples can only be argued that way, not shown.
- **Decision:** `tests/test_properties.py` uses Hypothesis to generate inputs and checks properties over
  them:
  - a code no table knows, in five places across the providers, comes out `UNMAPPED` with its exact raw
    value and a warning;
  - line amounts stay exact, derived totals add up to the cent, and any decimal survives the JSON writer
    digit for digit;
  - shuffling the captures changes nothing in the output;
  - dropping any subset of captures never crashes, and every record that points at a missing one says so;
  - a field no converter knows is kept in `provider_extensions`;
  - a mapping rule limited to some companies reaches exactly those (A-69).

  Runs are derandomized and keep no example database, so the suite stays deterministic and offline.
  Setting `PROPERTY_EXAMPLES` runs a deeper, randomized search. That search found two records pointing at
  a missing one without saying so: PrismHR deduction setup of an employee whose record wasn't fetched,
  and a UKG statement whose payroll wasn't. Both carry the note (A-40), and example tests pin them.
- **Why:** a property that holds over thousands of generated inputs is evidence the code isn't fitted to
  its examples, and a failing one names a minimal counterexample.

### A-43 Fixtures with live key aliases are validated on their contents
- **Evidence:** `#/components/schemas/PayrollResponseWithPagination` documents `payrollVouchers` and
  permits additional properties, so a fixture using the live alias `payrollVoucher` (A-16) would pass
  validation with *any* contents.
- **Decision:** before schema validation, the fixture checker translates known live aliases back to their
  documented names, per endpoint and at any depth of the body (`payrollVoucher` → `payrollVouchers`,
  `clientPayrollSchedule` → `clientPayrollSchedules`, and those of A-78), so the contents are validated
  against the real schema. Converters still receive the alias form, as live data has it.

## Optional extension: writing an employee

### A-63 Write path: a dry run into UKG Ready
- **Issue:** the brief invites an optional write path from canonical employee data to a destination
  tenant, done for real or as a dry run. The demo tokens can write, and the tenants are real provider test
  systems (A-04).
- **Decision:**
  - The write path is a dry run only (`python -m normalization write`). There is deliberately no way to
    send a plan, and no write request exists anywhere in the code.
  - The destination is UKG Ready. All three specs document request schemas, and one destination is enough
    to show the mapping; UKG's create flow is small and self-contained. UKG documents that creating an
    employee "covers the core fields of the employee" and that related data needs more calls, so a plan
    is two requests:
    1. `POST /v2/companies/{cid}/employees` (`#/schemas/105`);
    2. `POST /v2/companies/{cid}/compensation/history` (`#/schemas/32`), whose account ID comes from step 1.
  - Each request body is validated against UKG's own request schema, and the plan says whether it is
    valid. Valid against the schema is not the same as accepted: a real tenant can still refuse a body
    for reasons only it knows, such as a username already taken or a field it requires, and only a live
    write would show that.
  - A value the canonical record can't supply is a **gap** with its reason, never invented: the full SSN
    (only the last 4 digits are kept, A-23), a username when the source has none (isolved), a manager's
    destination account ID, a county (UKG addresses have none), and an effective date that was invalid at
    the source (A-46).
  - Destination defaults are listed separately. The only one is the address country "USA" when the
    source sends none, because UKG requires an ISO country and all three sources are US payroll systems.
  - Pay is taken on the employee's own basis: annual pay for salaried employees, the hourly rate for
    hourly ones, otherwise the first rate whose period UKG supports. Standard hours become UKG's
    milliseconds, and pay periods per year come from the canonical pay frequency.
  - `external_id` carries the canonical ID, so a created employee can be traced back to its source.
  - UKG's own `nickname` and second email round-trip: `name.nickname` (else the preferred name) and the
    `SECONDARY` email (else a personal one) fill UKG's `nickname` and `secondary_email` (A-82).
  - The plan only creates. The brief says "create or update"; an update would also need the
    destination's current record to compare against, which a dry run without a live destination doesn't
    have.
  - A non-active source status becomes a note, because UKG's `status` is read-only on create.
- **Results on the synthetic scenarios:** UKG employees round-trip into schema-valid requests. PrismHR
  employees' requests are valid too, except one whose effective date was invalid at the source. isolved
  employees' requests fail validation for the missing username, which is the honest answer.
