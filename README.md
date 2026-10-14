# Payroll data normalization: PrismHR, isolved and UKG Ready

This project reads company, employee, direct-deposit, deduction and payroll data from **PrismHR**,
**isolved** and **UKG Ready**, and converts it into one canonical model without losing what the source
data means:

- every code keeps its raw value;
- every amount stays exact;
- every derived number says how it was derived;
- anything the model doesn't map is kept, not dropped.

It runs locally and offline. The demo and the tests use seeded synthetic data shaped exactly like
each provider's API. Live demo tenants are needed only to fetch new data. The original brief is in
[ASSIGNMENT.md](ASSIGNMENT.md).

## Quick start

Python 3.11 or newer.

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m normalization demo    # normalize every provider's synthetic scenario
pytest                          # 190 tests, offline
mypy                            # static type check: no issues
```

`demo` prints one line per provider:

```
provider   companies  employees  deposits  elections  runs  paychecks  checks pass/fail  warnings  unavailable
prismhr            2          6         8          5     6          8              24/0        10            7
isolved            1          5         5          5     6          7              24/0         1            0
ukg-ready          1          5         6          2     4          4               2/0         7            4
```

The warnings are deliberate traps in the synthetic data: an invalid placeholder date, codes nobody
documents, a customer-named pay statement type, and endpoints that refuse or don't exist, as on the
live tenants. Each one is reported, not guessed. "Unavailable" counts requests that returned no data
when data may exist. Their records say so, so an empty list in the output always means "none"
(A-70).

It writes:

- `out/demo/<provider>/<record type>.json` and `summary.json`: canonical records, sorted by ID;
- `out/demo/<provider>/provenance.json`: what produced them: the bundle snapshot (with a SHA-256 of
  its files), the as-of date, the request outcomes, each mapping file (with its SHA-256), and the
  code version and git commit (A-71);
- `out/demo/canonical.sqlite`: all three providers in one database, linked by canonical IDs, with a
  `sources` table holding the same provenance.

```sql
-- every paycheck, with its employee and its reconciliation result
SELECT provider, first_name, last_name, pay_date, gross_wages, gross_pay, net_pay, checks_passed
FROM pay_statement_overview ORDER BY provider, pay_date;

-- deductions taken on paychecks, by canonical category, across providers
SELECT c.provider, d.category, COUNT(*), SUM(CAST(d.employee_amount AS REAL))
FROM deduction_lines d
JOIN pay_statements s ON s.id = d.pay_statement_id
JOIN companies c ON c.id = s.company_id
GROUP BY 1, 2;

-- employee taxes withheld, by canonical tax type and state, across providers
SELECT t.type, t.state, c.provider, SUM(CAST(t.amount AS REAL))
FROM tax_lines t
JOIN pay_statements s ON s.id = t.pay_statement_id
JOIN companies c ON c.id = s.company_id
WHERE t.paid_by = 'EMPLOYEE'
GROUP BY 1, 2, 3;
```

## Commands

| Command | What it does |
|---|---|
| `python -m normalization demo` | Normalizes the synthetic scenario of all three providers. Offline. |
| `python -m normalization normalize BUNDLE` | Normalizes one raw bundle, a fixture or a live fetch, into `out/`. `--as-of` fixes the date for time-dependent values. |
| `python -m normalization fetch --provider P` | Read-only fetch from the live demo tenants (`all` for every provider). `--normalize` also normalizes the result. |
| `python -m normalization write EMPLOYEES_JSON` | Dry run: the UKG Ready requests that would create these employees, validated against UKG's request schemas. Nothing is sent. |
| `python -m normalization review BUNDLE ...` | Collects every value still `UNMAPPED` into distinct decisions, with suggestions, and writes a report plus a mapping-file template per provider. |
| `python -m normalization schema` | Writes the canonical model's JSON Schemas to `schemas/`. |
| `python -m normalization coverage [BUNDLE ...]` | Writes [docs/FIELD_COVERAGE.md](docs/FIELD_COVERAGE.md): what happens to every source field. |
| `python scripts/generate_fixtures.py [--check]` | Regenerates the synthetic fixtures and golden files, or (`--check`) proves they are reproducible. |

### Live data (optional)

Put the organizer's key in `.env` as `DEMO_SIGNIN_API_KEY=...` (`.env` is gitignored), then:

```sh
python -m normalization fetch --provider all --normalize
```

The demo tenants are real provider test systems, and their tokens can write, so live access is
locked down (A-04):

- Every request passes a scope guard before it is sent: GET only, on the base URL `/signin`
  returned, to allowlisted read endpoints, for the demo company IDs only. Redirects are re-checked hop
  by hop.
- Credentials are scrubbed from everything saved.
- Raw responses go to `.discovery/` and normalized output to `out/`. Both are gitignored and never
  committed.

The live fetches of 2026-10-12 and 2026-10-13 normalize like this:

| Provider | Companies | Employees | Deposits | Elections | Runs | Paychecks | Checks passed |
|---|---:|---:|---:|---:|---:|---:|---:|
| PrismHR | 25 | 51 | 22 | 137 | 1,493 | 420 | 1,175 of 1,175 |
| isolved | 2 | 30 | 21 | 572 | 231 | 430 | 468 of 468 |
| UKG Ready | 1 | 15 | 5 | 0 (the tenant returns 404, A-12) | 89 | 61 | 60 of 60 |

## How it works

```
provider API --fetch (GET only)--> raw bundle -----> converter -----> canonical records --> JSON + SQLite
synthetic generator -------------> raw bundle        (one per          (Output)
 (validated against the provider's  (session.json +   provider)
  own published schemas)             captures/)
```

- A **raw bundle** has the same layout whether it came from a live fetch or the generator, so the
  converters can't tell the two apart.
- Each **converter** lives in `src/normalization/providers/<provider>/`. `codes.py` holds every code
  table, and each table cites its evidence. `convert.py` maps responses to records.

### The canonical model

Six record types: `Company`, `Employee`, `DirectDeposit`, `DeductionElection`, `PayrollRun` and
`PayStatement` (paycheck). They are linked by canonical IDs of the form
`{provider}:{tenant}:{entity}:{source ids}`. The full design is in
[docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md), and the JSON Schemas are in [schemas/](schemas/).
The main conventions:

- **Coded values** are `{value, raw, label, source_field}`. An unknown code becomes `UNMAPPED`, keeps
  its raw value, and gets a diagnostic. Customer-configured labels stay `UNMAPPED` with their label.
- **Money** is an exact decimal string, never a float and never rounded.
- **Rates** always carry their period (`per`). **Quantities** carry a unit: hours, units or unknown.
- **Percents** carry a scale. When a provider's scale (5 vs 0.05) isn't proven, the number stays null
  and the raw value is kept.
- **Derived values** are flagged, with their formula: UKG's gross and net, for example.
- **Time-dependent values** (is this deposit active? which pay record is current?) are evaluated at an
  explicit `as_of` date: the fetch date, or a fixed date for fixtures.
- **Lossless:** converters read every source field through a tracker, and whatever a record doesn't
  map goes into its `provider_extensions`, sanitized. The coverage report shows each field's fate. It
  tracks what converters read, so converters read only the values they map, and tests check that
  values they don't map survive (A-62).
- **Sensitive data:** SSNs and account numbers keep at most their last 4 digits, everywhere.
- **Paycheck lines are classified** in canonical terms: an earning's `kind` (how it is paid) and
  `category` (what it pays for: regular, overtime, vacation, ...), and a tax's `type` (federal income,
  Social Security, state unemployment, ...) with its `state` (A-67, A-68).
- **Diagnostics** on every record explain anything unusual: unmapped codes, invalid dates, data not
  fetched, amounts not finalized.
- **Unavailable is not empty:** a request that was refused or failed is reported on the records it
  would have fed, so their missing data reads as unknown, not none. A failure counts as an empty
  answer only where the provider documents or says so (A-70).
- **Reconciliation checks** on every paycheck are reported, never "fixed":
  - gross wages = the sum of the earning lines;
  - gross wages − non-cash earnings = gross pay;
  - gross pay − employee taxes − deductions = net;
  - payments = net.

### The evidence rule

A mapping is made only from the provider's own documentation, the provider's own label or
classification, or arithmetic on live data. Enum names alone are not evidence. Some findings this
rule produced, each recorded in [ASSUMPTIONS.md](ASSUMPTIONS.md):

- PrismHR's `salary` is per pay period, not annual (A-20). Its vouchers reconcile only once non-cash
  pay classes are excluded from net pay (A-32).
- isolved's `grossWages − grossPay` equals the paycheck's group-term life imputed income on every
  live check (A-28). Its pay frequency must be resolved by lookup *description*, never by ID (A-27).
- UKG Ready's hours are milliseconds (A-24), and its `base_rate` is the employee's base rate: overtime
  lines pay 1.5 times it (A-24). Its "Fringe" payment lines balance non-cash pay and pay nothing
  (A-58).
- The three providers mask differently: UKG returns full SSNs, PrismHR masks them. The output keeps the
  last 4 digits in every case (A-23).
- Tax types come from each provider's own codes and descriptions, and the arithmetic agrees: Social
  Security lines are exactly 6.2% of taxable wages, Medicare 1.45%. UKG names its state income tax
  only after the state (`SIT:WI` is "Wisconsin"), but it is taxed on the same wage base as federal
  income tax on 62 of 63 live statements (A-68).
- PrismHR documents an earning category for each pay code (`talxPayType`), but the live tenant leaves
  it blank. So PrismHR pay codes, like UKG's, wait for a person to classify them, while isolved's
  come from its own system earnings (A-67).
- Live data departs from each provider's own schema in specific, documented ways (A-16, A-47, A-52,
  A-61).

### Unknown values: review, then map with evidence

New tenants bring codes no table knows. They come out `UNMAPPED` with a warning, and are never
guessed. The loop for resolving them needs no code change (A-65):

```sh
python -m normalization review .discovery/prismhr/<run>     # 6,540 unmapped mentions -> 77 decisions
# fill in `value` and `evidence` in out/review/mappings-prismhr-<tenant>.json
python -m normalization normalize .discovery/prismhr/<run> --mappings out/review/mappings-prismhr-<tenant>.json
```

The rules for mapping files:

- A mapping only fills a value that would otherwise be `UNMAPPED`; it never overrides a documented
  code table.
- Every entry must carry written evidence, and the value must be valid for that field.
- A file names its tenant and applies to no other. A rule can be limited to some of the tenant's
  companies, because a customer's code can mean different things in two of its companies. The
  template limits each rule to the companies the value was seen in; widening it is a separate
  decision (A-69).
- Each resolved record notes which mapping and evidence resolved it. The output lists each mapping
  file used, with its hash and any rule that matched nothing, such as a mistyped company ID.

Because a mapping takes effect during conversion, everything downstream uses it: a newly classified
earning line, for example, lets gross pay be derived.

`review` also suggests values, locally and deterministically, without ever applying them (A-66):

- **Arithmetic, which is evidence.** For an unknown earning kind, it tests on every paycheck the line
  appears on whether the provider's own totals reconcile with the line as cash or as non-cash. For
  example: "net pay reconciles on 1 of 1 paychecks only if this line is not paid out". This separates
  cash from non-cash; it can't tell which non-cash kind. For an unknown tax code, it tests whether
  every line is exactly 6.2%, 1.45% or 0.9% of taxable wages: the Social Security, Medicare and
  Additional Medicare rates.
- **Similar names, which are only a hint.** It compares the unknown value and label with texts already
  mapped to the same canonical type, across all providers' code tables and the output. For example,
  "Leave - FMLA" is like ON_LEAVE (0.44). Where arithmetic has narrowed the kind, names only rank
  within it.

The template lists each field's allowed values and these suggestions. `value` and `evidence` stay
empty until a person fills them in.

## How it was built

1. **Discovery first.** We read the specs, then made read-only calls to each live demo tenant. Every
   response was saved, and each open question was settled with counts. For example: is UKG's `hours`
   a count or milliseconds? Does PrismHR's net pay include fringe? Each decision went into
   ASSUMPTIONS.md as issue, evidence, decision, why.
2. **The canonical model,** designed from that evidence, then reviewed and audited before any converter
   was written.
3. **One converter per provider,** each tested three ways:
   - on synthetic fixtures full of traps;
   - against golden files;
   - on the live data, where every reconciliation check passes.
4. **Tooling that checks the work:**
   - the fixture generator validates every response against the provider's published schema;
   - the coverage report accounts for every source field;
   - every output record validates against the exported JSON Schema;
   - fixtures and golden files must regenerate byte for byte.

AI assistance was used throughout, as the brief allows. Every mapping rests on cited spec text or
counted live evidence.

## Testing

`pytest` runs 190 offline tests (plus parametrized subtests). Nothing needs credentials or network.

- **Synthetic scenarios** (`fixtures/<provider>/brightside`) come from a seeded generator, and every
  response is validated against the provider's own published schema. They are full of real-world
  traps, all listed at the top of each `src/normalization/fixtures/<provider>.py`.
- **Golden files** (`tests/golden/`) pin the complete output. Tests also assert specific facts, such as
  "sequence 0 is the remainder account" or "the fringe is in gross wages but not gross pay".
- **Determinism:** `scripts/generate_fixtures.py --check` regenerates everything and compares it byte
  for byte.
- **Coverage and schema tests** check three things:
  - no field is both mapped and kept;
  - only crawl indexes and unneeded lookups go unread;
  - every golden record matches the exported JSON Schema.
- **Live client tests** reproduce scope, redirect and scrubbing attacks against a fake HTTP client.
- **Property tests** (`tests/test_properties.py`, Hypothesis) check rules that must hold for any
  input, not just the fixtures' (A-72):
  - a code no table knows comes out `UNMAPPED` with its raw value;
  - amounts stay exact to the cent;
  - the output doesn't depend on the order of captures;
  - a partial bundle never crashes and every dangling link is explained;
  - a field no converter knows is kept;
  - a mapping rule reaches exactly the companies it names.

  They run derandomized, so the suite stays deterministic. `PROPERTY_EXAMPLES=500 pytest
  tests/test_properties.py` searches deeper. The deep search found two links left dangling without an
  explanation, both now fixed and pinned by tests.

## Repository layout

```
src/normalization/
  canonical/          the model: records, value types, code enums, JSON Schema export
  providers/          one converter per provider (codes.py + convert.py), shared helpers
  fixtures/           the seeded synthetic scenario of each provider, and schema validation
  live/               the read-only client: sign-in, scope guard, crawl, fetch
  write/              the dry-run write path (UKG Ready)
  checks.py           paycheck reconciliation
  export.py           JSON and SQLite output
  coverage.py         the field coverage report
  mappings.py         mapping files and the review queue for unmapped values
  suggest.py          suggestions for that queue: arithmetic evidence and similar names
  source.py           tracked field access and value parsing
  sanitize.py         last-4 masking of sensitive values
fixtures/             generated synthetic bundles (committed)
tests/                tests and golden files
schemas/              JSON Schema of every canonical record type
docs/                 CANONICAL_MODEL.md, FIELD_COVERAGE.md, REFERENCE_AUDIT.md (organizer)
contracts/            the organizer's provider specs (untouched, hash-checked)
```

## Limitations

The details are in [ASSUMPTIONS.md](ASSUMPTIONS.md).

- **Refused or empty endpoints:** some endpoints are refused for the demo credentials, such as
  PrismHR garnishment and employer details and isolved's payroll and "corestream" endpoints (A-08 to
  A-10). UKG deduction setup returns 404 on the demo tenant. The converter supports it and is tested
  on synthetic data (A-12).
- **Payroll history:** live isolved payroll is historical, imported data, and all live UKG payrolls are
  still open (A-11, A-13).
- **Percent scales** are unproven for isolved and UKG deposits and deductions, so the number stays
  null with its raw value (A-29). Tax withholding setup is kept raw, not mapped (A-34).
- **Small live samples:** codes that never appeared in them are mapped from documentation only (A-07).
- **Unclassified codes:** PrismHR and UKG earning codes have no category until a mapping file gives
  one (A-67). State and local tax numbers that mean different things in different states stay
  `UNMAPPED`, as do PrismHR's state assessments (A-68).
- **Next steps for production use:**
  - per-record evidence tests in place of provider-wide rules (A-32 held on 420 vouchers, then one
    voucher broke it);
  - failed checks that name the likely missing component;
  - drift alerts from comparing each fetch's field coverage with the last;
  - an optional local LLM (for example via Ollama) as a third suggester, still proposing only, so the
    data never leaves the machine;
  - full pagination and incremental sync for large tenants.
- **Write path:** a dry run into UKG Ready only. The full SSN is not available by design, because the
  model keeps the last 4 digits (A-63).
