# Payroll data normalization: PrismHR, isolved and UKG Ready

This project reads company, employee, direct-deposit, deduction and payroll data from **PrismHR**,
**isolved** and **UKG Ready**, and converts it into one canonical model without losing what the source
data means: every code keeps its raw value, every amount stays exact, every derived number says how it
was derived, and anything the model doesn't map is kept, or dropped only for a stated reason, such as
being a copy of another value.

It runs locally and offline. The demo and the tests use seeded synthetic data shaped like each
provider's API; the live demo tenants are needed only to fetch new data. The brief is in
[ASSIGNMENT.md](ASSIGNMENT.md).

**Read next:** [ASSUMPTIONS.md](ASSUMPTIONS.md) for the design, the rules every mapping follows, the key
decisions and the known limitations, each linked to its evidence in
[docs/DECISION_LOG.md](docs/DECISION_LOG.md). The model itself is in
[docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md).

## Quick start

Python 3.11 or newer.

```sh
python3.11 -m venv .venv && source .venv/bin/activate   # or any Python 3.11+
pip install -e ".[dev]"
python -m normalization demo    # normalize every provider's synthetic scenario
pytest                          # 266 tests, offline
mypy                            # static type check: no issues
```

`demo` prints one line per provider:

```
provider   companies  employees  deposits  elections  runs  paychecks  checks pass/fail  warnings  unavailable
prismhr            2          6         8          6     6          8              24/0        11            7
isolved            1          5         5          6     7          7              24/0         2            0
ukg-ready          1          5         6          2     4          4               2/0        10            5
```

The warnings are traps built into the synthetic data, such as codes nobody documents and endpoints that
refuse, as on the live tenants; each is reported, not guessed. "Unavailable" counts requests that
returned no data when data may exist; their records say so (A-70).

It writes, under `out/demo/`:

- `<provider>/<record type>.json` and `summary.json`: the canonical records, sorted by ID;
- `<provider>/provenance.json`: what produced them, including the bundle's SHA-256, the mapping files
  and the git commit (A-71);
- `canonical.sqlite`: all three providers in one database, linked by canonical IDs.

```sql
-- every paycheck, with its employee and its reconciliation result
SELECT provider, first_name, last_name, pay_date, gross_wages, gross_pay, net_pay, checks_passed
FROM pay_statement_overview ORDER BY provider, pay_date;
```

## Commands

| Command | What it does |
|---|---|
| `python -m normalization demo` | Normalizes the synthetic scenario of all three providers. Offline. |
| `python -m normalization normalize BUNDLE` | Normalizes one raw bundle (a fixture or a live fetch) into `out/`. |
| `python -m normalization fetch --provider P` | Read-only fetch from the live demo tenants (`all` for every provider); `--normalize` also normalizes it. |
| `python -m normalization review BUNDLE ...` | Lists every value still `UNMAPPED`, with suggestions, and writes a mapping-file template. |
| `python -m normalization coverage [BUNDLE ...]` | What happens to every source field; with live bundles it writes [docs/FIELD_COVERAGE.md](docs/FIELD_COVERAGE.md). |
| `python -m normalization schema` | Writes the canonical model's JSON Schemas to `schemas/`. |
| `python -m normalization write EMPLOYEES_JSON` | Dry run: the UKG Ready requests that would create these employees, validated against UKG's schemas. Nothing is sent. |
| `python scripts/generate_fixtures.py [--check]` | Regenerates the synthetic fixtures, golden files and `fixtures/MANIFEST.json`, or proves they are reproducible. |

The reviewed mapping files in `mappings/` are applied by default, each to its own tenant only;
`--no-reviewed-mappings` shows the converters' output alone (A-86).

## Live data (optional)

Put the organizer's key in `.env` as `DEMO_SIGNIN_API_KEY=...` (gitignored), then run
`python -m normalization fetch --provider all --normalize`.

The demo tenants are real provider test systems and their tokens can write, so every request passes a
scope guard first: GET only, allowlisted endpoints, and only the companies `/signin` returned (A-04).
The crawl takes at most 25 employees per company (A-07). Raw responses go to `.discovery/` and output to
`out/`; both are gitignored.

The final live fetches (PrismHR on 2026-10-16, isolved and UKG on 2026-10-15) normalize like this:

| Provider | Companies | Employees | Deposits | Elections | Runs | Paychecks | Checks passed |
|---|---:|---:|---:|---:|---:|---:|---:|
| PrismHR | 25 | 194 | 64 | 591 | 4,525 | 2,403 | 6,804 of 6,807 |
| isolved | 2 | 45 | 35 | 10 | 231 | 430 | 543 of 543 |
| UKG Ready | 1 | 25 | 7 | 0 (the tenant returns 404, A-12) | 89 | 63 | 61 of 61 |

The 3 failed checks are two PrismHR vouchers that don't add up in PrismHR's own numbers; they are
reported, not adjusted (A-32).

## How it works

```
provider API --fetch (GET only)--> raw bundle --> converter (one per provider) --> canonical records --> JSON + SQLite
synthetic generator -------------> raw bundle
```

- A **raw bundle** has the same layout whether it came from a live fetch or the generator, so the
  converters can't tell the two apart.
- Each **converter** lives in `src/normalization/providers/<provider>/`: `codes.py` holds the code
  tables, each citing its evidence, and `convert.py` maps responses to records.
- The **canonical model** has six linked record types: `Company`, `Employee`, `DirectDeposit`,
  `DeductionElection`, `PayrollRun` and `PayStatement`, exported as JSON Schema in `schemas/`.
- **The evidence rule:** a value is mapped only from the provider's documentation, its own label or
  classification, or arithmetic on live data. Otherwise it stays `UNMAPPED` with its raw value and a
  diagnostic.

## Adding a provider

A fourth provider is one more converter; the other three don't change. Add its spec under
`contracts/<provider>/` and to the endpoint inventory (`live/endpoints.py`), a synthetic scenario in
`src/normalization/fixtures/<provider>.py`, and `providers/<provider>/codes.py` and `convert.py`,
registered in `providers.PROVIDERS`. The tests then fail until each gap has an answer: every documented
endpoint has a decision (A-74), every field is mapped, kept or dropped for a reason, every value read
reaches the output (A-62), and no missing value reads as zero (A-73).

## Testing

`pytest` runs 266 offline tests (plus parametrized subtests). Nothing needs credentials or network. They
include golden files pinning each scenario's whole output, schema validation of every fixture against the
provider's published spec, byte-for-byte fixture reproducibility, a field coverage check, a test that
plants a marker in each field the scenarios fill and requires it in the output, a missing-vs-zero sweep,
and Hypothesis property tests.

## How it was built

Discovery came first: read the specs, then read-only calls to each demo tenant, with every open question
settled by counts and recorded in the decision log. Then the canonical model, then one converter per
provider. Outside reviews followed: each confirmed finding was fixed or recorded as a limitation, and a
recurring kind of miss got a test that catches it. AI assistance was used throughout, as the brief
allows; every mapping rests on cited spec text or counted live evidence.

## Repository layout

```
src/normalization/    canonical model, converters, live client, fixtures generator, checks, export
fixtures/             generated synthetic bundles, with MANIFEST.json
mappings/             reviewed mapping files, one per tenant (A-86)
scripts/              generate_fixtures.py, and the read-only discovery helpers
tests/                tests and golden files
schemas/              JSON Schema of every canonical record type
docs/                 DECISION_LOG.md, CANONICAL_MODEL.md, FIELD_COVERAGE.md, REFERENCE_AUDIT.md (organizer)
contracts/            the organizer's provider specs (untouched, hash-checked)
```

## Limitations

The full list is in [ASSUMPTIONS.md](ASSUMPTIONS.md#known-limitations). The main ones: some endpoints
refuse the demo credentials, the live data is a sample of 25 employees per company, codes a customer
configured wait for a mapping file, unproven percent scales stay raw, and the write path is a dry run
into UKG Ready that only creates employees.
