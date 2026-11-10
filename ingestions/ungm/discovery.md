# Discovery: ungm

Phase 1. Written by `source-scout`. Evidence only, no design decisions.
Every `- Label:` line must be answered; `make status ID=ungm` lists what is missing.

## Source
- Institution / portal URL:
- Access type (web):
- robots.txt and Terms of Service:
<!-- Access type: public API, authenticated API, web portal or file drop.
     robots.txt and ToS: what they allow, the link and the date you read them. -->

## Probe evidence
Probes run through `scrapagents.stealth.PlaywrightObscuraRouter` (obscura.sh):
`make probe ID=ungm URL=<url>` appends the rows below.

| Date | URL | Status | Content type | Blocked by (captcha / waf / none) |
| :--- | :--- | :--- | :--- | :--- |
| 2026-11-09 | https://www.ungm.org/robots.txt | 403 | text/html | waf |
| 2026-11-09 | https://www.ungm.org/Public/Notice | 403 | text/html | waf |

## Structure found
- Endpoints or DOM entry points:
- Pagination and ordering:
- Authentication:
- Payload formats:
- Estimated volume and change rate:
<!-- Payload formats: JSON, XML, HTML, CSV, PDF or DOCX. -->
