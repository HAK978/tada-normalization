# Assumptions, decisions and limitations

This is the short version: how the project is built and why, the rules every mapping follows, the
decisions that shape the data, where the data differed from what we expected, and what the output doesn't
do. Each point links to its entry in the [decision log](docs/DECISION_LOG.md), which records the issue,
the evidence, the decision and why for all 91 judgment calls. The IDs (A-01 to A-91) are the ones the code
and the tests cite.

**Evidence** means the specs in `contracts/` (for isolved, the primary snapshot only), the provider's own
labels and classifications, or arithmetic on live data from read-only requests to the three demo tenants.
Live data is quoted as counts and code values only.

**In brief.** All five data types from all three providers are normalized into six linked record types.
A value is mapped only when the evidence says what it means; anything else keeps its raw value and gets a
diagnostic, and whatever a record doesn't map is kept in its `provider_extensions`, so nothing is lost.
Not normalized: tax withholding setup and some PrismHR plan rules (kept as sent), percents whose scale
isn't proven (kept raw), and codes a customer configured, which wait for a person to classify them in a
mapping file. The live data is a sample of up to 25 employees per company, and a few endpoints refuse
the demo credentials; each such gap is reported on the records it affects. The
[known limitations](#known-limitations) list all of it.

## Design and architecture

```
provider API --GET only--> raw bundle --> converter, one per provider --> canonical records --> JSON + SQLite
synthetic generator -----> raw bundle                                                      + summary, provenance
```

- **Raw data first.** A fetch saves every response exactly as sent, as a bundle, before anything is
  interpreted. A mapping can be corrected and rerun without calling the provider again, and the evidence
  for each decision stays on disk. The synthetic generator writes the same format, validated against each
  provider's own schemas, so the converters can't tell test data from live data, and every test runs
  offline [A-06], [A-43].
- **A canonical model as the hub.** Each provider maps into one model, never into another provider's
  shape: six record types (company, employee, direct deposit, deduction election, payroll run, paycheck),
  linked by canonical IDs and exported as JSON Schema ([docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md)).
  Every coded value keeps its raw value and source field beside the canonical one. A fourth provider
  would need one new converter; the README's [Adding a provider](README.md#adding-a-provider) lists
  the steps and the tests that hold them.
- **One converter per provider,** with its code tables in one module, each table citing its evidence.
  Converters read through a tracker, so a report can say what happened to every source field [A-62].
- **Decisions as data.** What only a person can settle, such as a customer's own codes or enum names
  nobody defines, goes into mapping files, one per tenant, each rule with its evidence written down,
  instead of into code [A-65], [A-69], [A-86]. A review queue collects the values still unmapped and
  suggests answers from arithmetic and similar names, which a person accepts or rejects [A-66].
- **Live access that can't do harm.** The demo tokens can write and can reach other companies, so every
  request passes a scope guard: GET only, allowlisted endpoints, and only the companies `/signin` returned
  [A-04], [A-05]. Credentials and live records never reach Git [A-06].
- **Output for people and for tools:** JSON per record type to read and diff, SQLite to query the linked
  records with plain SQL, a summary of counts and checks, and a provenance file naming the bundle and its
  hash, the mapping files and the commit that produced the output [A-36], [A-71].
- **Interfaces:** the CLI (`demo`, `fetch`, `normalize`, `review`, `coverage`, `schema`, `write`; see the
  README), and the formats between the stages: the bundle, the canonical JSON Schemas, the SQLite tables
  and the mapping files.
- **Stack:** Python 3.11+, Pydantic v2 for the model and its JSON Schemas, `jsonschema` for fixture
  validation, httpx, pytest and Hypothesis [A-03]. The starter scaffold was replaced and `contracts/`
  left untouched, in a repository with no link to the organizer's [A-01], [A-02].
- **The optional write path** is a dry run into UKG Ready: canonical employees become UKG's create
  requests, validated against UKG's request schemas, and nothing is sent [A-63].

## Rules that apply everywhere

1. **Evidence or nothing.** A value is mapped only from the provider's documentation, its own label or
   classification, or arithmetic on live data. A name alone isn't evidence, however plain it looks: UKG's
   `CHECKING` stays `UNMAPPED` until a person confirms it in a reviewed mapping file [A-26], [A-86].
   Whatever the data doesn't establish is reported, never assumed [A-64], and a customer's own labels
   stay `UNMAPPED`, with the label kept [A-35].
2. **Nothing is lost.** Whatever a record doesn't map is kept in its `provider_extensions`, sanitized. The
   coverage report accounts for every source field, and a test plants a marker in each mapped or kept
   field to prove its value reaches the output [A-62].
3. **Missing is not zero, and unavailable is not empty.** A value the provider didn't send is never read
   as 0, "no" or "none" [A-73]. A refused or failed request is reported on the records it would have fed,
   so their data reads as unknown; a failure counts as an empty answer only where the provider documents
   or says so [A-70].
4. **Exact and explicit.** Money is an exact decimal, never rounded, even when the provider sent a
   floating-point artifact [A-59]. Rates carry their period, quantities their unit, derived values their
   formula. A percent's scale (5 vs 0.05) is proven only by arithmetic on the provider's own amounts,
   never by its size: PrismHR deduction percents are, on 214 of 214 paycheck lines, and every other
   percent keeps its raw value with its scale `UNVERIFIED` [A-29]. PrismHR and isolved amounts are
   assumed to be USD; UKG states its currency [A-31].
5. **Dates.** Only UKG's documented "beginning of time" and "end of time" (1900-01-01, 3000-01-01) become
   open-ended; other far-off dates are kept, with a note. UKG's expiration dates are exclusive, as
   documented, and PrismHR and isolved end dates are assumed inclusive [A-25]. Anything time-dependent is
   evaluated at an explicit `as_of` date, so the output never depends on the day it runs [A-33].
6. **Checks are reported, never fixed.** Each paycheck's arithmetic is checked, and a mismatch is
   reported, not adjusted [A-54].
7. **Privacy.** SSNs and account numbers keep at most their last 4 digits everywhere in the output, and
   the endpoints that exist to list full SSNs are never called [A-23].

## Key decisions, by data type

### Company
- **A company is the business the employees work for:** a PrismHR client, an isolved legal company with
  its client as the parent, a UKG company. The data can't say who files the taxes, so the service
  arrangement, assigned employers and tax IDs are separate fields, in each provider's own terms, and none
  is labeled "employer of record" [A-30].
- PrismHR refuses employer names and EINs to the demo credentials, and UKG has no company details
  endpoint; both gaps are reported [A-09], [A-15]. UKG's EIN lookup lists one EIN while its payrolls name
  two, so the company holds both [A-60]. PrismHR's company contacts are mapped [A-84].

### Employee
- **What is normalized:** identifiers, name, personal details, contacts (emergency contacts, dependents
  and beneficiaries, each with its roles), addresses, phones and emails, employment status and dates, job
  and organization, and compensation, each with its history where the provider has one [A-76], [A-77].
  The rest is kept as sent, chiefly tax withholding setup [A-34].
- **Status comes from the provider's own classification,** never from a customer's status name:
  PrismHR's documented class, with the client's own code kept beside it [A-89]; isolved's system status,
  through the client's own status table [A-48]; UKG's two values, which its termination dates confirm
  [A-55].
- **Pay is proven by arithmetic.** PrismHR's `salary` is per pay period: `salary × periods = annualPay`
  for every salaried employee [A-20]. Its undocumented rate basis `A` behaves as annual on all 18
  employees that have it, and maps so, with a note [A-19]. UKG's amount, hourly pay and standard hours
  (documented in milliseconds) agree on all 27 live records with an amount [A-56]. isolved's pay
  frequency resolves through its lookup's description, never its ID [A-27].
- **A contractor is a worker classification, not a pay type** [A-39]. Organization units keep the
  provider's own dimension names, such as "Location" and "Department", and none is read as a canonical
  department [A-75].
- **Demographics:** UKG documents gender and citizenship as bare names, so they stay `UNMAPPED` until a
  reviewed mapping file confirms them, as the demo tenant's file does [A-79], [A-86]. PrismHR's gender
  codes map from the definitions in its new-hire schema [A-44].

### Direct deposits
- **Methods are mapped per source field.** PrismHR's `PN` is "percentage of net after fixed" on a
  deposit but "Percent of Net after Taxes" on an HSA deposit, so the two map differently, and an HSA
  deposit says who funds it [A-37].
- **UKG's methods map only where a label defines them:** `FULL`, `FLAT_AMOUNT` and `GROSS_EARNING`.
  `NET_PAY` and `DIRECT_DEPOSIT_PER_OF_REMAINDER` have no label anywhere and stay `UNMAPPED` [A-26].
- **No deposit percent has a proven scale,** since none of their owners has a fetched paycheck, so every
  deposit percent stays raw [A-29]. UKG's deprecated deposit endpoint still answers [A-14].

### Deductions
- **A calculation keeps its basis.** PrismHR documents 29 methods, which tell gross pay from gross
  earnings and hours worked from hours paid [A-41]. isolved's categories come from the system pay item
  each client item is built on, linked by title, because codes repeat [A-49].
- **Deduction setup filed under benefits is still deduction setup:** PrismHR's retirement loans are
  elections [A-87]. Its 401(k) plan rules, flex plans and benefit adjustments are kept as sent with the
  employee, because the elections payroll applies already come from its deduction endpoints [A-91].
  isolved's garnishment "Limit" has no stated basis and stays raw [A-88].
- **Refused or missing setup is never read as "no deductions":** PrismHR's garnishment details (another
  endpoint says which 3 employees have garnishments the output can't show), isolved's "corestream"
  endpoints, and UKG's deduction setup, which answers 404 on the demo tenant but is supported and tested
  on synthetic data [A-08], [A-83], [A-10], [A-12].

### Payroll runs and paychecks
- **Gross means one thing for every provider.** `gross_wages` is every earning counted in gross,
  non-cash ones included; `gross_pay` is the part actually paid. PrismHR's `totalEarnings` and isolved's
  `grossWages` are gross wages, isolved's `grossPay` is gross pay, and the rest is derived and flagged
  [A-54], [A-28], [A-32]. That is what makes paychecks reconcile: 7,408 of 7,411 live checks pass, and the
  3 that don't are source inconsistencies, reported [A-32].
- **Units proven by arithmetic:** UKG's pay-statement hours are milliseconds, since
  `(hours ÷ 3,600,000) × rate = amount` on the live lines, and overtime lines pay 1.5 times the rate
  [A-24].
  PrismHR's `payAmount` is the line total, not the "pay per hour or unit" its description says [A-18].
- **Line kinds and categories come from each provider's own classification:** PrismHR pay classes and
  TALX types, isolved system earnings, UKG line types. A customer's own earning code waits for a mapping
  file [A-53], [A-58], [A-67]. Tax types come from the provider's codes and descriptions, checked against
  the statutory 6.2% and 1.45% [A-68].
- **Links:** paychecks join their runs on explicit keys, and a record pointing at one that wasn't fetched
  says so [A-40]. isolved's live payroll is historical imported data, and every UKG payroll is still
  open; both are normalized as they are, with a note [A-11], [A-13].

## Where the data differed from what we expected

| What we found | What we did | Entry |
|---|---|---|
| Endpoints refused to the demo credentials: PrismHR garnishment and employer details, isolved's payroll list and "corestream" endpoints | still called; each refusal is reported on the records it affects, so their data reads as unknown | [A-08], [A-09], [A-10], [A-70] |
| UKG's deduction setup answers 404 "Unresolvable URL" for every employee | supported and tested on synthetic data; live employees say their deductions are unknown | [A-12] |
| PrismHR sends keys under other names than its spec (`payrollVoucher`, `person.employerId`, ...) | read both spellings; the fixtures send both | [A-16], [A-78] |
| PrismHR's payroll schedule swaps a code and its description | follow the live data | [A-90] |
| PrismHR loan dates are documented as YYYY-DD-MM but sent as YYYY-MM-DD | parse them as sent | [A-17] |
| PrismHR lists each employee loan in two endpoints, `getDeductions` and `getEmployeeLoans` | one election per loan, matched on code and loan ID; a value the two disagree on is kept and flagged | [A-64] |
| PrismHR sends `0000-01-01` and `9999-12-31` as dates | the first becomes null with a warning; the second stays a date, with a note | [A-46] |
| PrismHR birth dates arrive unmasked, though documented as masked | kept as employee data; SSNs and account numbers keep at most their last 4 | [A-23] |
| Codes undocumented for their field: PrismHR batch statuses, citizenship `Y`, pay-rate basis `A` | `UNMAPPED` with the raw value, unless live evidence settles one: `A` behaves as annual, and batch status `COMP` holds only printed vouchers | [A-21], [A-45], [A-19] |
| PrismHR documents an earning category for each pay code, but every live pay code leaves it blank | categories wait for a mapping file | [A-67] |
| Live responses break their own schemas: nulls, missing required fields, wrong types, extra fields | the converters accept them; the fixtures reproduce the common ones, and validation allows exactly those | [A-47], [A-52], [A-61] |
| isolved sends marital status as a description where a one-letter code is documented | map it by the lookup's description, keeping what was sent | [A-52] |
| isolved's `veteranStatusNotSpecified` disagrees with its documentation | kept as sent | [A-81] |
| UKG's EIN lookup lists one of the two EINs its payrolls name | the company holds both, with a note | [A-60] |
| UKG's cost-center tree 1 answers "Cost Center not used." while 8 employees are assigned to it | unavailable, not an empty tree | [A-75] |
| UKG's deposit endpoint is deprecated, and its end-of-support date has passed | still called with the documented header; it answers every time | [A-14] |
| One UKG amount is a floating-point artifact, 2.4699999999999998 | kept exactly, with a note naming the penny amount | [A-59] |
| Two PrismHR vouchers don't reconcile | reported, not adjusted | [A-32] |

## What was fetched

Read-only fetches of the demo tenants ran from 2026-10-12 to 2026-10-16. Each one after the first full
fetch returned the same records as the one before, apart from what newly added endpoints and request
options brought. The
crawl takes at most 25 employees per company, and for isolved and UKG each paycheck's owner first: 194 of
668 PrismHR employees, 45 of 138 isolved and 25 of 103 UKG. Every documented read endpoint, 855 in all,
is fetched (80 of them) or has a recorded reason it isn't, and a test keeps it that way [A-07], [A-74].

## Known limitations

- **Refused or failing on the demo tenants:** PrismHR garnishment details and employer names and EINs,
  isolved's payroll list and "corestream" endpoints, and UKG deduction setup (404; supported and tested on
  synthetic data). Each is reported on the records it affects, and the 3 PrismHR employees with
  garnishments the output can't show say so [A-08], [A-09], [A-10], [A-12], [A-83]. isolved's
  year-to-date accumulations and Corestream payroll schedules were refused when tried, and aren't fetched
  [A-74].
- **Not fetched because they were empty live:** documented employee data such as PrismHR deduction
  arrears, garnishment payment history and override rates, isolved benefit elections and UKG additional
  compensation. A tenant that has such data would need them added to the crawl, with a converter that
  keeps or maps them [A-74]. isolved contacts are fetched but empty live, so their mapping rests on the
  documentation [A-77].
- **Kept as sent, not normalized:** tax withholding setup [A-34]; PrismHR's 401(k) plan rules, flex plans
  and benefit adjustments [A-91]; isolved's garnishment limit [A-88]. UKG's W-2 and 1099 flags have no
  definitions, which leaves its worker classification empty [A-34].
- **Percents:** only PrismHR deduction percents have a proven scale. Deposit, isolved deduction and UKG
  percents keep their raw value [A-29].
- **Codes that need a person:** customer-configured statuses and types, PrismHR and UKG earning codes,
  UKG values documented only by name, and state and local tax numbers that mean different things in
  different states stay `UNMAPPED` until a mapping file resolves them. The demo tenant's reviewed file
  covers UKG's plain names; a new tenant needs its own [A-35], [A-65], [A-67], [A-68], [A-86].
- **SSNs:** PrismHR employees have no last 4 digits, because `getEmployee` masks every digit and the
  endpoint with the digits returns full SSNs, which is deliberately not called. isolved employees get
  theirs from a fetched check, 21 of 45 [A-23], [A-50].
- **A sample of each tenant:** 926 PrismHR and 6 UKG paychecks and 3 retirement loans belong to employees
  whose records weren't fetched, and each says so [A-07]. History is shallow live, mostly one row per
  employee [A-76]. isolved's live payroll is historical and UKG's all open [A-11], [A-13]. Codes that
  never appeared live are mapped from documentation only, so behavior on other tenants rests on the
  evidence rules and the tests [A-72], [A-73].
- **Scope, as we read the brief:** skills, education, certifications, training, time off and benefit
  enrollment aren't normalized. Benefits appear as paycheck contributions and as deduction setup, and what
  a provider sends inside the employee record anyway is kept [A-62], [A-74].
- **Provider risk:** UKG's deprecated deposit endpoint can stop working [A-14], and UKG offers no company
  details [A-15].
- **Write path:** a dry run into UKG Ready that creates employees and doesn't update them. A request that
  is valid against UKG's schema can still be refused by a real tenant, which only a live write would show
  [A-63].

## What the organizer asked, and where it is done

Every instruction in the brief (`ASSIGNMENT.md`) and the organizer's reference notes
(`docs/REFERENCE_AUDIT.md` and the lookup files), with where it is met.

| Instruction | Source | Where it is done |
|---|---|---|
| Normalize company, employee, direct-deposit, deduction and payroll data from all three providers | brief | six linked record types ([docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md)), one converter per provider |
| Complete employee data: profile and contact, status and dates, job and organization, compensation, "all available employee fields" | brief | [Employee](#employee); every documented endpoint decided [A-74]; scope as we read it in the [known limitations](#known-limitations) |
| Direct deposits: account types, allocations, amounts or percentages, priority, status and dates | brief | [A-26], [A-29], [A-37], [A-86] |
| Deductions: setup and in payroll, codes and types, amounts or percentages, rules and dates | brief | [A-41], [A-49], [A-87], [A-88], [A-91] |
| Payroll: runs and periods, paychecks, earnings, hours, gross and net, taxes, deductions, contributions | brief | [A-24], [A-54], [A-67], [A-68] |
| Keep company and employee relationships | brief | canonical IDs (model §2.1), [A-40]; a sampled fetch says what it doesn't link [A-07] |
| Document every gap, assumption and decision, with why | brief | this file and the [decision log](docs/DECISION_LOG.md) |
| Document data that fails or looks wrong: the issue, the decision, the reasoning | brief | [Where the data differed](#where-the-data-differed-from-what-we-expected), with each entry's reasoning in the log |
| Choose and explain the design, architecture and interfaces | brief | [Design and architecture](#design-and-architecture) |
| Design your own canonical schemas and enums | brief | `schemas/`, [docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md) |
| Generate and validate your own synthetic test data | brief | [A-06], [A-43] |
| "Add your seed, schema validation and generation manifest" | starter stub | `fixtures/MANIFEST.json` [A-06] |
| Preserve the meaning of the source data | brief | [Rules that apply everywhere](#rules-that-apply-everywhere): [A-26], [A-35], [A-62], [A-64], [A-73] |
| Lookup files are partial; "undocumented meanings remain unknown" | brief, lookup files | [A-85], [A-86] |
| Use isolved's primary snapshot only | brief | every citation and the fixture validation use only the primary |
| Read UKG's pages for bindings, parameters and schemas | brief | [A-14], [A-61], the endpoint inventory [A-74] |
| Tests deterministic, offline, without credentials | brief | [A-06] |
| Keep tokens and downloaded records out of Git | brief | [A-04], [A-06] |
| Optional: write canonical employees to a provider | brief | [A-63], a dry run, as the brief permits |
| Status classes and client-configured status IDs are "separate domains"; preserve the distinction | reference notes | [A-89] |
| isolved reads employment statuses from client details | reference notes | [A-48] |
| UKG earning and deduction codes are client-specific | reference notes | [A-35], [A-67] |
| Don't infer units from a name or a value's magnitude; UKG milliseconds are field-specific | reference notes | [A-24], [A-29], [A-56] |
| Per-code meanings are not inferred from enum labels; examples aren't closed enums | lookup files | [A-26], [A-79], [A-86] |

[A-01]: docs/DECISION_LOG.md#a-01-our-own-repository-with-no-link-to-the-organizers
[A-02]: docs/DECISION_LOG.md#a-02-the-starter-scaffold-was-replaced
[A-03]: docs/DECISION_LOG.md#a-03-stack
[A-04]: docs/DECISION_LOG.md#a-04-live-access-is-read-only-and-scope-guarded
[A-05]: docs/DECISION_LOG.md#a-05-one-exception-prismhr-employer-lookups
[A-06]: docs/DECISION_LOG.md#a-06-live-data-is-never-committed-tests-use-synthetic-data
[A-07]: docs/DECISION_LOG.md#a-07-what-was-fetched
[A-08]: docs/DECISION_LOG.md#a-08-prismhr-garnishment-details-are-refused
[A-09]: docs/DECISION_LOG.md#a-09-prismhr-employer-names-and-eins-are-refused
[A-10]: docs/DECISION_LOG.md#a-10-isolveds-payroll-list-and-corestream-deduction-endpoints-are-refused
[A-11]: docs/DECISION_LOG.md#a-11-isolved-has-only-historical-imported-payroll
[A-12]: docs/DECISION_LOG.md#a-12-ukg-deduction-setup-documented-but-this-tenant-answers-404
[A-13]: docs/DECISION_LOG.md#a-13-ukg-payroll-runs-are-all-open
[A-14]: docs/DECISION_LOG.md#a-14-ukgs-deprecated-direct-deposit-endpoint-still-works
[A-15]: docs/DECISION_LOG.md#a-15-ukg-has-no-company-details-endpoint
[A-16]: docs/DECISION_LOG.md#a-16-prismhr-response-keys-differ-from-the-spec
[A-17]: docs/DECISION_LOG.md#a-17-prismhr-loan-dates-are-yyyy-mm-dd-not-the-documented-yyyy-dd-mm
[A-18]: docs/DECISION_LOG.md#a-18-prismhr-earning-payamount-is-the-line-total
[A-19]: docs/DECISION_LOG.md#a-19-prismhr-pay-rate-basis-a-is-undocumented-it-behaves-as-annual
[A-20]: docs/DECISION_LOG.md#a-20-prismhr-salary-is-per-pay-period
[A-21]: docs/DECISION_LOG.md#a-21-prismhr-batch-codes-that-the-spec-doesnt-document
[A-23]: docs/DECISION_LOG.md#a-23-masking-differs-by-provider-the-output-keeps-at-most-the-last-4-digits
[A-24]: docs/DECISION_LOG.md#a-24-ukg-pay-statement-hours-are-milliseconds
[A-25]: docs/DECISION_LOG.md#a-25-open-ended-dates-and-span-boundaries
[A-26]: docs/DECISION_LOG.md#a-26-ukg-direct-deposit-methods-only-labeled-values-are-mapped
[A-27]: docs/DECISION_LOG.md#a-27-isolved-pay-frequency-resolved-by-description-never-by-id
[A-28]: docs/DECISION_LOG.md#a-28-isolved-check-buckets-and-its-two-gross-figures
[A-29]: docs/DECISION_LOG.md#a-29-percent-scale-5-vs-005
[A-30]: docs/DECISION_LOG.md#a-30-a-company-is-the-business-not-the-legal-employer
[A-31]: docs/DECISION_LOG.md#a-31-currency
[A-32]: docs/DECISION_LOG.md#a-32-prismhr-gross-and-net-reconcile-from-the-line-items
[A-33]: docs/DECISION_LOG.md#a-33-time-dependent-fields-use-an-explicit-as_of-date
[A-34]: docs/DECISION_LOG.md#a-34-tax-withholding-setup-is-kept-not-normalized
[A-35]: docs/DECISION_LOG.md#a-35-customer-configured-labels-stay-unmapped
[A-36]: docs/DECISION_LOG.md#a-36-output-json-and-sqlite
[A-37]: docs/DECISION_LOG.md#a-37-hsa-deposits-are-a-different-kind-of-deposit
[A-39]: docs/DECISION_LOG.md#a-39-contractor-status-is-not-a-pay-type
[A-40]: docs/DECISION_LOG.md#a-40-record-links-and-paycheck-to-run-joins
[A-41]: docs/DECISION_LOG.md#a-41-deduction-calculations-keep-their-basis
[A-43]: docs/DECISION_LOG.md#a-43-fixtures-with-live-key-aliases-are-validated-on-their-contents
[A-44]: docs/DECISION_LOG.md#a-44-prismhr-gender-codes
[A-45]: docs/DECISION_LOG.md#a-45-prismhr-citizenship-arrives-as-the-documented-description-not-the-code
[A-46]: docs/DECISION_LOG.md#a-46-prismhr-placeholder-dates
[A-47]: docs/DECISION_LOG.md#a-47-live-prismhr-responses-dont-match-their-own-schema-in-three-ways
[A-48]: docs/DECISION_LOG.md#a-48-isolved-employment-status-through-the-clients-status-table
[A-49]: docs/DECISION_LOG.md#a-49-isolved-deduction-categories-come-from-the-client-pay-items-system-classification
[A-50]: docs/DECISION_LOG.md#a-50-isolved-ssn-last-4-comes-from-check-records
[A-52]: docs/DECISION_LOG.md#a-52-live-isolved-employee-records-dont-match-their-own-schema-in-two-ways
[A-53]: docs/DECISION_LOG.md#a-53-isolved-earning-kinds-come-from-the-system-earning-each-pay-item-is-built-on
[A-54]: docs/DECISION_LOG.md#a-54-gross-pay-and-gross-wages-mean-the-same-thing-for-every-provider
[A-55]: docs/DECISION_LOG.md#a-55-ukg-employee-status
[A-56]: docs/DECISION_LOG.md#a-56-ukg-pay-amounts-hours-and-pay-periods
[A-58]: docs/DECISION_LOG.md#a-58-ukg-pay-statement-line-types-and-fringe-payments
[A-59]: docs/DECISION_LOG.md#a-59-one-amount-arrived-as-a-binary-floating-point-number
[A-60]: docs/DECISION_LOG.md#a-60-ukg-eins-the-lookup-doesnt-list-them-all
[A-61]: docs/DECISION_LOG.md#a-61-live-ukg-responses-dont-match-their-own-schema-in-five-ways
[A-62]: docs/DECISION_LOG.md#a-62-every-source-field-is-mapped-kept-or-dropped-for-a-stated-reason
[A-63]: docs/DECISION_LOG.md#a-63-write-path-a-dry-run-into-ukg-ready
[A-64]: docs/DECISION_LOG.md#a-64-unknown-conflicting-or-failed-source-data-is-reported-never-assumed
[A-65]: docs/DECISION_LOG.md#a-65-unknown-values-are-resolved-by-mapping-files-with-evidence-not-by-code-changes
[A-66]: docs/DECISION_LOG.md#a-66-suggestions-for-unmapped-values-arithmetic-first-similar-names-as-a-hint-never-applied
[A-67]: docs/DECISION_LOG.md#a-67-earning-categories-what-a-line-pays-for-from-the-providers-own-classification
[A-68]: docs/DECISION_LOG.md#a-68-tax-types-the-providers-own-codes-and-descriptions-checked-against-statutory-rates
[A-69]: docs/DECISION_LOG.md#a-69-mapping-files-belong-to-one-tenant-and-a-rule-can-be-limited-to-companies
[A-70]: docs/DECISION_LOG.md#a-70-unavailable-is-not-empty
[A-71]: docs/DECISION_LOG.md#a-71-every-output-records-what-produced-it
[A-72]: docs/DECISION_LOG.md#a-72-rules-that-must-hold-for-any-input-are-tested-on-generated-inputs
[A-73]: docs/DECISION_LOG.md#a-73-missing-is-never-read-as-zero-no-or-none
[A-74]: docs/DECISION_LOG.md#a-74-every-documented-read-endpoint-is-fetched-or-has-a-recorded-reason
[A-75]: docs/DECISION_LOG.md#a-75-organization-units-keep-the-providers-own-names
[A-76]: docs/DECISION_LOG.md#a-76-employment-and-job-history
[A-77]: docs/DECISION_LOG.md#a-77-contacts-emergency-contacts-dependents-and-beneficiaries
[A-78]: docs/DECISION_LOG.md#a-78-more-prismhr-keys-that-differ-from-the-spec-among-them-the-employees-employer
[A-79]: docs/DECISION_LOG.md#a-79-ukg-demographics-stay-unmapped-until-a-mapping-file-confirms-them
[A-81]: docs/DECISION_LOG.md#a-81-isolved-veteran-and-disability-status
[A-83]: docs/DECISION_LOG.md#a-83-prismhr-whether-an-employee-has-garnishments
[A-84]: docs/DECISION_LOG.md#a-84-prismhr-company-contacts
[A-85]: docs/DECISION_LOG.md#a-85-the-organizers-lookup-references-agree-with-the-code-tables
[A-86]: docs/DECISION_LOG.md#a-86-codes-documented-only-by-name-are-confirmed-by-a-person-in-a-reviewed-mapping-file
[A-87]: docs/DECISION_LOG.md#a-87-prismhr-retirement-loans
[A-88]: docs/DECISION_LOG.md#a-88-isolved-garnishment-limits
[A-89]: docs/DECISION_LOG.md#a-89-prismhr-status-and-type-the-documented-class-not-the-clients-code
[A-90]: docs/DECISION_LOG.md#a-90-prismhr-payroll-schedule-the-code-and-its-description-are-swapped
[A-91]: docs/DECISION_LOG.md#a-91-prismhr-retirement-plans-flex-plans-and-benefit-adjustments
