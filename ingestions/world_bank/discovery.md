# Discovery: world_bank

Phase 1. Written by `source-scout`. Evidence only, no design decisions.
Every `- Label:` line must be answered; `make status ID=world_bank` lists what is missing.

## Source
- Institution / portal URL: The World Bank Group — Projects & Operations Procurement Portal (`https://projects.worldbank.org/en/projects-operations/procurement?srce=both`).
- Access type (web): Public web portal (Angular SPA) backed by an unauthenticated public REST/JSON API (`https://search.worldbank.org/api/v2/procnotices`). Probed via `scrapagents.stealth.PlaywrightObscuraRouter` (`obscura.sh` over CDP) with HTTP 200 responses and no WAF or CAPTCHA challenges (`blocked_by: none`).
- robots.txt and Terms of Service: `https://projects.worldbank.org/robots.txt` (read 2026-11-11) states `User-agent: * / Allow: *` and only disallows internal AEM/archive paths (`*/apps/*`, `*/wbg/services/*`, `*/en/webarchives/archive*`, `*/misc*`, `*/conf/*`, `*/downloadstats/*`, `*/wbg/aem/*`), explicitly permitting `/en/projects-operations/procurement`. `https://search.worldbank.org/robots.txt` returns HTTP 404 (no robots restrictions). World Bank Terms of Use for Datasets (`https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets` and `https://www.worldbank.org/en/about/legal/terms-and-conditions`, read 2026-11-11) license World Bank datasets under **Creative Commons Attribution 4.0 International (CC BY 4.0)**, explicitly permitting copying, extracting, downloading, adapting, and distributing data for non-commercial and commercial purposes subject to attribution ("The World Bank: Procurement Notices").
<!-- Access type: public API, authenticated API, web portal or file drop.
     robots.txt and ToS: what they allow, the link and the date you read them. -->

## Probe evidence
Probes run through `scrapagents.stealth.PlaywrightObscuraRouter` (obscura.sh):
`make probe ID=world_bank URL=<url>` appends the rows below.

| Date | URL | Status | Content type | Blocked by (captcha / waf / none) |
| :--- | :--- | :--- | :--- | :--- |
| 2026-11-11 | https://projects.worldbank.org/robots.txt | 200 | text/plain | none |
| 2026-11-11 | https://projects.worldbank.org/en/projects-operations/procurement?srce=both | 200 | text/html | none |
| 2026-11-11 | https://search.worldbank.org/robots.txt | 404 | application/json | none |
| 2026-11-11 | https://search.worldbank.org/api/v2/procnotices?format=json | 200 | application/json | none |
| 2026-11-11 | https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00480372 | 200 | text/html | none |

## Structure found
- Endpoints or DOM entry points: Web portal listing at `https://projects.worldbank.org/en/projects-operations/procurement?srce=both` and notice detail pages at `https://projects.worldbank.org/en/projects-operations/procurement-detail/<id>` (e.g., `OP00480372`). The SPA dynamically populates its table and detail views from the backing REST endpoint `https://search.worldbank.org/api/v2/procnotices?format=json&apilang=en&rows=<n>&os=<offset>`, which returns structured JSON under the `procnotices` key (`id`, `notice_type`, `noticedate`, `notice_lang_name`, `notice_status`, `submission_deadline_date`, `submission_deadline_time`, `project_ctry_name`, `project_id`, `project_name`, `bid_reference_no`, `bid_description`, `procurement_group`, `procurement_method_code`, `procurement_method_name`, `contact_name`, `contact_email`, `contact_phone_no`, `contact_organization`, `contact_address`, `contact_ctry_name`, `contact_web_url`, `submission_date`, `notice_text`).
- Pagination and ordering: Offset-based pagination via query parameters `rows` (page size, e.g., 50 or 100) and `os` (0-based starting offset), with total record count reported in the top-level `total` field (`426,458` historical notices). Records are returned in reverse chronological order (newest `submission_date` / `noticedate` first) by default and support country (`qterm`, `project_ctry_exact`), notice type, and date filters.
- Authentication: None required. Both the web portal (`projects.worldbank.org`) and the backing search API (`search.worldbank.org/api/v2/procnotices`) are publicly accessible without API keys, session cookies, or bearer tokens.
- Payload formats: HTML (web portal shell and embedded HTML inside `notice_text`), JSON (primary structured notice feed from `/api/v2/procnotices`), PDF (optional linked procurement documents or bidding attachments when referenced in notice details).
- Estimated volume and change rate: Total historical archive is ~426,458 procurement notices globally; active/recent procurement notices represent roughly 500–2,000 open opportunities at any time, with ~50–150 new or updated notices published daily across all regions (including Latin America and the Caribbean / Ecuador).
<!-- Payload formats: JSON, XML, HTML, CSV, PDF or DOCX. -->
