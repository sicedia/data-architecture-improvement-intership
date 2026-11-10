# Discovery: caf

Phase 1. Written by `source-scout`. Evidence only, no design decisions.
Every `- Label:` line must be answered; `make status ID=caf` lists what is missing.

## Source
- Institution / portal URL: CAF - Banco de Desarrollo de América Latina y el Caribe (https://www.caf.com). Convocatorias portal: https://www.caf.com/es/trabaja-con-nosotros/convocatorias/.
- Access type (web): Web portal protected by Imperva / Incapsula Web Application Firewall (WAF). Probed through `scrapagents.stealth.PlaywrightObscuraRouter` (obscura.sh over CDP). Note: www.caf.com serves an incomplete TLS certificate chain (missing intermediate CA 'Sectigo Public Server Authentication CA DV R36'); required injecting the intermediate cert into Obscura's CA store. Direct and automated requests trigger Incapsula challenge (HTTP 403 / `_Incapsula_Resource`).
- robots.txt and Terms of Service: robots.txt (probed 2026-11-10, https://www.caf.com/robots.txt): returns HTTP 200 intercepted by Incapsula WAF, which returns an HTML challenge containing `<META NAME="robots" CONTENT="noindex,nofollow">` and `/_Incapsula_Resource` script. Terms of Service (https://www.caf.com/es/terminos-y-condiciones/, read 2026-11-10): All content copyright CAF. Automated access is not explicitly licensed and is actively blocked by perimeter WAF controls.

## Probe evidence
Probes run through `scrapagents.stealth.PlaywrightObscuraRouter` (obscura.sh):
`make probe ID=caf URL=<url>` appends the rows below.

| Date | URL | Status | Content type | Blocked by (captcha / waf / none) |
| :--- | :--- | :--- | :--- | :--- |
| 2026-11-10 | https://www.caf.com/robots.txt | 200 | text/html | none |
| 2026-11-10 | https://www.caf.com/es/trabaja-con-nosotros/convocatorias/ | 403 | text/html | waf |

## Structure found
- Endpoints or DOM entry points: Primary entry point `https://www.caf.com/es/trabaja-con-nosotros/convocatorias/` (listing of consultancies, acquisitions, and funding calls). Detail pages link to terms of reference (PDF) and application forms. When accessed without solving Incapsula challenges, the page serves an iframe with `Request unsuccessful. Incapsula incident ID`.
- Pagination and ordering: Listings are ordered by deadline / publication date, with category and country filters. Automated navigation requires handling Incapsula cookies (`incap_ses`, `visid_incap`).
- Authentication: No user account needed for public listings, but network-level authentication / proof-of-work challenge is enforced by Imperva WAF.
- Payload formats: HTML (listing and detail pages), PDF (bases de concurso, términos de referencia, pliegos). Under Invariant 4, only PDF documents go to Apache Tika.
- Estimated volume and change rate: Estimated 50-150 active and closed convocatorias per year across member countries. Change rate is low to moderate (approx. 2-5 updates per week).
