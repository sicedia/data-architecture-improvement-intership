---
name: new-source
description: Run the design-time workflow of a new institutional ingestion, from discovery to a signed blueprint, coordinating source-scout, source-assessor, silver-designer and arch-reviewer and stopping for the human gates H1 and H2. Use when the user wants to add a new source or website.
disable-model-invocation: true
---

# New source: Discovery -> Assessment -(H1)-> Blueprint -(H2)-> Implement

You coordinate; the four agents do the work; **humans sign the gates**. Read `AGENTS.md` first.
State lives in `ingestions/<id>/state.yml` and is changed only by `make advance` (phase) and by a
human running `make sign` (gates). `make status ID=<id>` tells you where a source is at any time.

## 0. Inputs
You need: `ID` (snake_case), `TEAM` (sistemas_internos, iditi, inteligencia_artificial,
seguridad_informacion), `TYPE` (api, database, file, web), the entry URL(s) and the dataset names.
Ask the user once for whatever is missing. One site is one `ID`: a source never shares a dossier,
a DAG or a Pool with another.

## 1. Discovery
`make new-ingestion ID=<id> TEAM=<team> TYPE=<type> DATASET=<dataset>`, then delegate to
**source-scout**. When `make status ID=<id>` shows no blockers, run `make advance ID=<id>`.
If the scout reports a captcha, a WAF block or Terms that forbid automation, stop and tell the user.

## 2. Assessment, then Gate H1 (human)
Delegate to **source-assessor**. Then **stop**: summarise the decision and risks for the user and
give them the command to run **in their own terminal** (never run it yourself, it refuses agents):

    make sign ID=<id> GATE=h1 BY="<their name>"

Wait for the user to say it is signed, then `make advance ID=<id>`. A `no-go` ends the workflow here.

## 3. Blueprint, review, then Gate H2 (human)
Delegate to **silver-designer**, then **arch-reviewer**. If `make review ID=<id>` fails or the
verdict is `changes requested`, send the findings back to silver-designer and review again (at most
three rounds, then ask the user). When the review passes and the verdict is `approve`, **stop** and
give the user the H2 command:

    make sign ID=<id> GATE=h2 BY="<their name>"

Wait for the user, then `make advance ID=<id>` (it refuses a stale review).

## 4. Hand-over
The dossier is now in phase `implement`. Generate what the platform derives from the blueprint:
`make generate-dags IDS=<id>` for the DAG, and add the contract to `DBT_CONTRACTS` for
`make generate-bronze generate-dbt`. Implementation and verification (phases 4 and 5) happen in this repository: the contract moves
to `configs/contracts/<id>/`, the declaration to `configs/ingestions/<id>.yml`, the extractor to
`python/scrapagents/extractors/<id>/`; `make advance` checks they exist, and a human closes the PR gate. Producto OI models for this
source are designed with the owner now, and `make check-gates` allows them because H1 and H2 are signed.

## Rules you never break
- Never edit `state.yml`, never run `make sign`, never fake an approval.
- Every browser access to a source goes through `make probe` (stealth router).
- No LLM or agent logic in anything that will run in production (invariant 1).
