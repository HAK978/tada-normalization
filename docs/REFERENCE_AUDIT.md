# Existing integration reference audit

Reviewed **2026-10-09** for the organizer-requested personal **private** repository
`Niwant/tada-ai-normalization-take-home`. No candidate invitations or public
publication are part of this update. Review method: artifact inspection, source
provenance comparison and published-license/terms review. This is not a separate
vendor approval or legal certification.

## Documented examples restored

The organizer clarified that provider-documented sample payloads should be
included. The prior removal interpreted the original no-dummy-response brief
as applying to embedded documentation examples; this clarification supersedes
that interpretation. The current pack restores all source example annotations,
request/response samples, parameter examples and fenced sample code/payloads.
They are labeled **illustrative provider documentation**, not customer exports
or guaranteed production behavior. Candidates still generate and validate their
own seeded fixtures and adversarial cases.

Only literal authentication-token/encoded-credential examples are redacted.
isolved has two token redactions and one encoded-auth redaction in each snapshot;
UKG has 70 token-like redactions across visible documentation. Duplicate hidden
clipboard copies and active HTML behavior are omitted while visible samples
and schemas are retained. Exact hashes and counts are in the provider manifests.
PrismHR restores 340 source example annotations and all eight embedded renderings;
UKG's extracted JSON Schema bundle restores 101 source example annotations.
Provider redistribution permission and candidate-sharing status are unchanged.

## Private-upload authorization

After reviewing the disclosed permission gaps, the organizer explicitly instructed
**“Yeah push those as well”** on 2026-10-09. This is the recorded authorization
for including the located isolved and UKG references in this personal private
repository. It does not establish a provider license or a candidate-sharing grant.
The earlier withholding decisions below describe the initial review; the private
upload instruction supersedes them for this storage action only.

The update includes both distinct isolved Swagger version-6 snapshots, with the
361-path snapshot designated primary. It also includes all 381 UKG HTML pages as
passive derivatives, and 478 parsed JSON Schema blocks extracted from those pages.
UKG's files are clearly identified as cached reference documentation, not an
invented or official OpenAPI contract. XML schemas and 18 opaque schema blocks
remain in the HTML. Source and derivative hashes and modification counts are in
[isolved's manifest](../contracts/isolved/SOURCE_MANIFEST.json) and
[UKG's manifest](../contracts/ukg-ready/SOURCE_MANIFEST.json).

The initial private-upload derivative removed embedded examples. The subsequent
clarification above restores them in the current pack. No customer lookup
responses or independent fixture suite was copied or generated.

Each provider still has exactly one lookup-reference JSON. isolved's 11 domains
and UKG's 15 domains contain literal explicit enum values with source pointers;
per-code meanings not documented by those arrays remain null. These intentionally
partial references do not define candidate canonical enums or completed mappings.
Candidate distribution and public sharing remain pending.

## Initial review decision (before the private-upload instruction)

- **Include PrismHR:** its exact existing OpenAPI artifact explicitly declares
  Apache 2.0. The initial derivative omitted examples; the current derivative restores them
  after the organizer's clarification, with attribution and the full license text.
- **Withhold isolved:** two Swagger snapshots were located, but neither declares
  a license and no applicable redistribution grant was found in the sources searched.
- **Withhold UKG Ready:** cached HTML documentation was located, but no standalone
  Swagger/OpenAPI file or applicable redistribution grant was found.

OpenAPI/Swagger specifies a contract format. The format itself does not supply
copyright or contractual permission to redistribute a particular document.
Private storage also does not establish redistribution rights.

## Source inventory and provenance

Paths below identify the existing `TadaAI/full-stack` integration repository;
they are provenance references, not copied integration implementation files.
The reference tree is tracked in source commit
`d834b89265ab80af464d45381bd46e13e72a95a3` (2026-05-01, `chat2`). That commit date
does not establish the provider's publication date, original download date or
current API version.

| Source | Format / snapshot metadata | Decision |
| --- | --- | --- |
| `references/prism/prism_api_specs.json` | PrismHR Services API; OpenAPI 3.0.1; API 2025.09; 450 paths / 1,168 schemas; 3,109,295 source bytes | Licensed derivative included |
| `chat/src/providers/prism/prism_api_specs.json` | Byte-identical duplicate of the PrismHR reference above | No duplicate copied |
| `references/isolved/api_docs.json` | isolved REST API; Swagger 2.0; API version 6; 361 paths / 538 definitions; 1,888,054 bytes; 20 enum locations | Initially withheld; now private derivative included |
| `isolved_doc.json` | isolved REST API; Swagger 2.0; API version 6; 344 paths / 516 definitions; 1,781,586 bytes; 20 enum locations | Initially withheld; now private alternate included |
| `references/saashr-rest-public/` | 381 HTML reference pages, including REST v2 routes and embedded JSON/XML schemas; no standalone OpenAPI artifact located | Initially withheld; now private derivative included |

Source SHA-256 values:

- PrismHR: `e1d9c05933d9bf0a8ccc416d483ec5bf4a2d41929d615daf44427c65e64b71e2`.
- isolved references snapshot: `ee126ab98e819872bbf1049137dacc2fb9d16dbd23a76d5ef3a6926c139e8300`.
- isolved root snapshot: `e8c009506a07d8466c176c995ab861143ccf54df47f92110a1f377860b24599f`.
- UKG HTML tree index: `3bff9aa28d6fbcf63a55ba88216178e5fcd88c5f313146e63827daf3e6b56559`.
  Index algorithm: sort HTML paths relative to that folder; hash the concatenation
  of UTF-8 path, NUL, raw 32-byte SHA-256 of file contents, and newline for each.
  This identifies the inspected tree; it is not a vendor-issued checksum.

## PrismHR inclusion basis and modifications

The exact source artifact's `/info/license` names **Apache 2.0 License** and links
to the [official Apache license](https://www.apache.org/licenses/LICENSE-2.0).
The artifact-specific declaration is the distribution basis used here; the full
license is [included](../contracts/prismhr/LICENSE.apache-2.0.txt), along with
[attribution and change notices](../contracts/prismhr/NOTICE.md). No separate
original NOTICE file was found beside the snapshot. Existing attribution and
license metadata were retained. This basis applies to the artifact and its
derivatives, not unrelated provider pages, customer data or Tada implementation.

The current distributed derivative retains all 340 source example annotations,
embedded descriptive sample payloads, formal paths, schema constraints, required
fields and defaults. It adds provenance and prominent illustrative-example and
modification notices. Authentication examples are redacted if present; the
artifact records zero such redactions for this PrismHR snapshot.

Current distributed SHA-256:
`9cb87857940095cf868ed666a70f9092e33d9aa26bcad3c46cb60dad3eff5978`.

The [partial lookup reference](../contracts/prismhr/lookup-reference.json) contains
eight domains and 43 documented code entries. Every domain retains its source
description and every entry cites the derivative's field description. The
snapshot contains no formal `enum` arrays; descriptive code lists are explicitly
distinguished from closed enums. No canonical mappings or enums are supplied.

The [official PrismHR API getting-started guide](https://ies.prismhr.com/docs/prismhr/docs/sp_help/Content/PD/API/Task%20Sheets/API_Getting_Started_PrismHR.htm)
links to the [API reference site](https://api-docs.prismhr.com/) and a customer
resource-center download. The current upstream artifact could not be independently
retrieved/refreshed in this review: the reference page is a JavaScript application,
and the checked direct API-host document URLs returned 404. The exact local
snapshot's embedded license is the evidence used, rather than a claim of a
fresh vendor approval or latest API version. [PrismHR's general website terms](https://www.prismhr.com/terms-of-use/)
also describe separate agreements/designated notices; this audit relies on the
artifact's specific license declaration for that artifact.

## isolved and UKG permission gaps

Neither isolved Swagger snapshot has an `/info/license` or `termsOfService`
declaration. The [published isolved terms and conditions](https://www.isolvedhcm.com/legal/agreements/terms-and-conditions)
restrict copying/modifying documentation absent an applicable grant or consent
(section 2.2(b)(viii)). These published terms are context, not a determination of
which executed agreement governs Tada's integration.

[UKG website terms](https://www.ukg.com/terms-of-use) restrict redistribution of
site materials. The [UKG developer policy](https://developer.ukg.com/proplatform/docs/developer-policy)
includes UKG Ready and refers to governing customer agreements. The
[customer terms index](https://www.ukg.com/legal/customer-terms) does not establish
that a particular signed agreement permits this hiring distribution. No such
agreement or grant was found in the searched sources. A cached folder name
containing `public` does not itself establish a redistribution license.

Searches covered relevant local integration reference/document paths in
`full-stack` and `phoenix`, Slack provider/documentation/permission terms,
Drive provider-related Swagger/OpenAPI/license/agreement metadata, and email
provider-related agreement/contract/license/permission subjects. These were
bounded searches, not an exhaustive legal inventory. Customer exports, payroll
records, credential files and response dumps were not copied into this repository.
No agreement is asserted to be absent everywhere.

To release the remaining materials, provide an applicable license, executed
agreement clause or written provider grant covering personal private GitHub
storage and hiring-candidate distribution of the contract and derived lookup
reference. Confirm any audience, redaction and tool restrictions. Then obtain the
authorized artifact, review its contents and document version/checksum/changes.
UKG additionally needs a standalone authorized contract or an explicitly agreed
alternative reference scope; the cached HTML tree is not an OpenAPI file.

## Lookup semantics discovered in the integrations

Internal handlers obtain important lookup values dynamically. PrismHR retrieves
client status/type codes through the client-codes endpoint. isolved reads
employment statuses from client details. UKG earning/deduction codes are
client-specific; prefixes used by Tada's lookup helper are Tada conventions,
not evidence of universal provider codes. No customer lookup responses or Tada
helper code were included.

The PrismHR reference documents four configurable lookup sources with empty
entries. Its documented status classes and benefit statuses are separate domains
from configurable status IDs. Candidates must preserve that distinction and
generate their own synthetic open identifiers where permitted by the contract.

## Field-specific UKG duration evidence

The inspected cached HTML does contain explicit millisecond descriptions for
particular fields. The following are factual summaries of inspected schema text,
not a claim of an official OpenAPI contract:

| Cached source under `references/saashr-rest-public/res/` | Inspected field / evidence |
| --- | --- |
| `__v2__companies__(cid)__time-entries.html`, lines 1077–1079 | The schema describes `total` as an integer measured in milliseconds |
| `__v2__companies__(cid)__employees__(aid)__pay-info.html`, lines 797–799 | The schema describes `standard_work_day` as an integer measured in milliseconds |

This establishes evidence in the cached snapshot for those exact fields. It
does not establish the current live API version, units of every UKG time field,
permission to distribute the HTML, or a completed source-to-canonical mapping.
Do not infer units from the provider name or a numeric value's magnitude. An
approved candidate pack still needs endpoint/field/version-specific evidence.
