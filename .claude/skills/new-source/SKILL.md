---
name: new-source
description: Guided interactive workflow to initialize, probe, review, and generate declarative Airflow DAGs for new web/API sources. Interactively prompts the user for source parameters (ID, TEAM, URL, DATASET), coordinates design agents (scout, assessor, designer, reviewer), presents review artifacts at Gates H1 and H2 with clear decision choices (Accept, Reject/No-go, Reload), and automates pipeline generation (DAG, Bronze, dbt) upon human sign-off.
disable-model-invocation: false
---

# Interactive Source Scaffolding & DAG Generator (`new-source`)

> **CORE PRINCIPLE:** The agent acts as the proactive **executor and interviewer** (collecting inputs, probing portals, drafting contracts, and compiling code), while the human acts as the **decision-maker and approver** at Gate H1 and Gate H2.

---

## Workflow Overview

```text
[0. Interactive Setup] ──> [1. Scout & Probe] ──> [2. Assessment] ──(Gate H1: Human)
                                                                            │
                                                                            ▼
[Done: Airflow Live]  ◄── [4. Auto-Generate]  ◄── (Gate H2: Human) ◄── [3. Blueprint & Review]
```

---

## Step 0: Interactive Parameter Collection

Before executing any commands, interview the user to collect the necessary parameters. Never require the human to format command-line flags manually.

Prompt the user for:
1. **Target URL:** The entry point portal, listing, or API endpoint (e.g., `https://portal.example.gov/tenders`).
2. **Source ID (`ID`):** Short unique identifier in `snake_case` (e.g., `sercop`, `world_bank`). Suggest a sensible default derived from the domain.
3. **Owning Team (`TEAM`):** Ask the user to select one of the allowed teams:
   - `sistemas_internos`
   - `iditi`
   - `inteligencia_artificial`
   - `seguridad_informacion`
4. **Main Dataset (`DATASET`):** Name of the primary entity (e.g., `tenders`, `opportunities`, `grants`). Default: `records`.
5. **Source Type (`TYPE`):** Default to `web` for portals requiring DOM/scraping, or `api` for REST/JSON endpoints.

---

## Step 1: Scaffolding and Automated Discovery

Once the inputs are gathered:
1. Scaffold the dossier:
   ```bash
   make new-ingestion ID=<id> TEAM=<team> TYPE=<type> DATASET=<dataset>
   ```
2. Probe the target URLs using Obscura over CDP:
   ```bash
   make probe ID=<id> URL="<target_url>"
   ```
3. Act as **`source-scout`**:
   - Inspect `ingestions/<id>/discovery.md` and complete all mandatory `- Label:` lines (ToS, robots.txt, DOM structure, pagination, anti-bot observations).
   - Ensure the probe table records response status, content type, and WAF/Captcha detection.
4. Verify readiness:
   ```bash
   make status ID=<id>
   ```
   If no blockers remain, advance:
   ```bash
   make advance ID=<id>
   ```

---

## Step 2: Assessment and Gate H1 (Human Decision Point)

1. Act as **`source-assessor`**:
   - Turn discovery evidence into a structured risk evaluation in `ingestions/<id>/assessment.md`.
   - Evaluate:
     - Legal/ToS terms and licensing.
     - Anti-bot risks (stealth profile and Airflow Pool slot allocation).
     - Personal data risks under LOPDP (Ecuador).
     - Triage classification (only PDF/DOCX to Apache Tika).
     - Refresh cadence and persistence strategy.

2. **Present Gate H1 to the Human:**
   - Link the file directly: `ingestions/<id>/assessment.md`.
   - Display a concise executive briefing summarizing:
     - Feasibility status.
     - Anti-bot / WAF status.
     - Personal data presence.
     - Recommended decision (`go` or `no-go`).
   - Present the human with 3 clear choices:
     - **Option 1: [Approve (Go)]**
       Instruct the human to run the signing command in their terminal (or provide the one-click instruction):
       ```bash
       make sign ID=<id> GATE=h1 BY="<Human Name>"
       ```
       Once signed, execute `make advance ID=<id>` to proceed to Phase 3.
     - **Option 2: [Reject (No-go)]**
       Update `assessment.md` with `- Decision: no-go` and rationale. Terminate workflow cleanly.
     - **Option 3: [Reload / Adjust]**
       Prompt for adjusted URLs or crawler delay settings, re-run `make probe`, and re-generate `assessment.md`.

---

## Step 3: Blueprint, Architecture Review & Gate H2

1. Act as **`silver-designer`**:
   - Create `ingestions/<id>/contract.yml` defining the typed schema (`primary_key`, column types, nullability, descriptions).
   - Create `ingestions/<id>/blueprint.yml` configuring the acquisition parameters, Airflow Pool, and dbt tags.

2. Act as **`arch-reviewer`**:
   - Run the mechanical architectural audit:
     ```bash
     make review ID=<id>
     ```
   - Verify compliance with the 5 invariants and dry-run code generation.
   - Record findings and verdict (`approve` or `changes requested`) in `ingestions/<id>/review.md`.

3. **Present Gate H2 to the Human:**
   - Link the files directly: `ingestions/<id>/blueprint.yml` and `ingestions/<id>/review.md`.
   - Present an executive summary of the schema grain, primary key, and reviewer verdict.
   - Present 3 clear choices:
     - **Option 1: [Approve H2]**
       Human confirms and executes in terminal:
       ```bash
       make sign ID=<id> GATE=h2 BY="<Human Name>"
       ```
       Once signed, execute `make advance ID=<id>` to move to `implement`.
     - **Option 2: [Request Changes]**
       User provides feedback on columns or keys; `silver-designer` updates files and re-runs `make review`.
     - **Option 3: [Cancel / Abort]**
       Safely remove the dossier or keep it on hold.

---

## Step 4: Fully Automated Pipeline Compilation & Verification

After Gate H2 is approved, automate all subsequent steps without human burden:

1. Promote design contracts:
   - Move contract to `configs/contracts/<id>/<dataset>.yml`.
   - Move ingestion config to `configs/ingestions/<id>.yml`.
   - Scaffold the extractor package in `python/scrapagents/extractors/<id>/`.

2. Compile deterministic artifacts:
   ```bash
   # Generate declarative YAML DAG for Airflow
   make generate-dags IDS=<id>

   # Generate typed Bronze DDL & apply to PostgreSQL
   make generate-bronze DBT_CONTRACTS="configs/contracts/<id>/<dataset>.yml"
   make bronze-apply

   # Generate Staging & Intermediate dbt SQL models
   make generate-dbt DBT_CONTRACTS="configs/contracts/<id>/<dataset>.yml"
   ```

3. Validate the platform:
   ```bash
   make airflow-parse   # Ensure Airflow detects the YAML DAG without errors
   make validate        # Validate lint, unit tests, contracts, and human gates
   ```

4. Notify the user:
   - Provide the DAG ID (`ingest__<id>`).
   - Confirm that the DAG is now visible in the Airflow UI at `http://127.0.0.1:8080`.
   - Instruct the human to sign the final PR gate when ready:
     ```bash
     make sign ID=<id> GATE=pr BY="<Human Name>"
     ```

---

## Rules you never break
- Never edit `state.yml`, never run `make sign`, never fake an approval.
- Every browser access to a source goes through `make probe` (stealth router).
- No LLM or agent logic in anything that will run in production (invariant 1).
