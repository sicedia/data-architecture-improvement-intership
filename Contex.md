# PROJECT CONTEXT & ARCHITECTURE SPECIFICATION (`AGENTS.md`)

> **TARGET AUDIENCE:** Autonomous AI Agents (`Claude Code`, `source-scout`, `source-assessor`, `silver-designer`, `arch-reviewer`).
> **CORE PRINCIPLE:** AI operates strictly at **Design-Time** to generate deterministic artifacts. **Run-Time** execution is 100% deterministic and free of LLM inference.

---

## 1. SYSTEM OVERVIEW & ARCHITECTURAL INVARIANTS

This platform ingests, normalizes, and governs unstructured and structured data from external institutions into a unified analytical product (**Producto OI - Opportunity Intelligence**). 

### Mandatory Architectural Invariants
1. **Zero AI at Run-Time:** Never embed LLM calls, dynamic prompts, or non-deterministic agent logic inside production extractors, Airflow DAGs, or dbt models.
2. **Single Source of Truth for Contracts:** All schemas, validation rules, and canonical mappings live in this repository (`configs/contracts/`, `configs/ingestions/`) and generate bronze, dbt and DAGs via YAML & Jinja templates. Never duplicate a contract elsewhere. CEDIA is a reference only, not a dependency.
3. **Browser access through Obscura (`obscura.sh` + `playwright`):** `obscura.sh` is a headless browser written in Rust and built for AI agents; it is the *destination* of every browser session. All browser-based discovery probes (`source-scout`) and production web extractors requiring DOM navigation use `playwright`, but instead of opening a local Chromium on the extractor host, Playwright connects to Obscura over the Chrome DevTools Protocol (`connect_over_cdp`, endpoint `OBSCURA_CDP_URL`, bearer token `OBSCURA_CDP_TOKEN`). Using Obscura does not replace the legal review: a site's Terms of Service, `robots.txt` and any block (WAF, captcha) are recorded as findings for Gate H1.
4. **Stream-to-Rust Integrity & Binary Triage (`SourceRuntime` / `RustWorker`):** Python extractors stream raw byte payloads directly to the native Rust binary (`RustWorker` / `SourceRuntime`). Rust computes SHA-256 hashes, persists raw objects to S3 `Landing`, and **filters/inspects payloads so that ONLY complex binary documents (e.g., PDF, DOCX) are routed to Apache Tika**, bypassing Tika entirely for structured payloads (JSON, XML, HTML, CSV).
5. **Strict Human-in-the-Loop (HITL) Gates:** Agents must halt execution and await explicit human sign-off at **Gate H1** (Viability Assessment), **Gate H2** (Blueprint/Contract Approval), and final **PR Merge**.

---

## 2. TECHNOLOGY STACK & TOOLING MATRIX

### 2.1 Design-Time (Agentic Harness)
| Component | Technology / Version | Agentic Role & Responsibility |
| :--- | :--- | :--- |
| **Core Orchestrator** | Claude Code | Primary repository orchestrator, scaffolding executor (`make new-ingestion`), and multi-agent coordinator. |
| **Discovery Probes & Browser** | Python (`playwright`, `pytest`) + `obscura.sh` (headless browser in Rust, reached over CDP) | Used by `source-scout` to run ephemeral probe scripts that connect to Obscura, map DOM/API structures, and detect and report WAF, Captcha and ToS blocks. |
| **Contract Engine** | YAML & Jinja2 | Read from `configs/` of this repository to compile data dictionaries, quality rules, and DAG/dbt generation templates. |

### 2.2 Run-Time (Deterministic Infrastructure)
| Component | Technology / Version | Operational Responsibility |
| :--- | :--- | :--- |
| **Workflow Orchestrator** | Apache Airflow `3.4.0` | Latest stable release (with native YAML DAG importer / AIP-85 support). Parses declarative `.yml` configurations generated at design-time to instantiate and schedule deterministic DAGs. |
| **Extractor & Browser Layer** | Python + `playwright` + `obscura.sh` | Executes production extraction from institutional web portals/APIs: Playwright drives the Obscura browser over CDP (`OBSCURA_CDP_URL`) and streams raw bytes directly to the Rust worker. |
| **SourceRuntime (`RustWorker`)** | Rust `1.80` (`tokio`, `sha2`) | Native high-concurrency binary packaged with Python. Computes SHA-256 hashes, validates integrity, dispatches raw files to S3 `Landing`, and **acts as a smart document filter**: routes lightweight/structured data directly to PostgreSQL `bronze` and forwards **only complex binaries** to Apache Tika. |
| **Binary Parser** | Apache Tika Server `4.1.0` | Invoked exclusively by `RustWorker` when `Landing` payloads are identified as complex binary documents (PDF, DOCX, etc.) to extract plain text (`.txt`). |

### 2.3 Data Warehouse, Lakehouse & Governance
| Component | Technology / Version | Storage / Modeling Responsibility |
| :--- | :--- | :--- |
| **Object Storage (Landing)** | RustFS S3 | Immutable Data Lake storing raw payloads and binaries under Hive-style partitioning. |
| **Data Warehouse** | PostgreSQL `16` | Hosts raw `bronze` (`JSONB` + quarantine tables) and analytical schemas managed by dbt. |
| **Transformation Engine** | dbt Core `1.12.3` (`dbt-postgres 1.10.1`) | Manages SQL transformations across `Staging`, `Intermediate`, and `Producto OI` layers. |
| **Data Catalog & Lineage** | OpenMetadata `1.4.2` | Automatically ingests Airflow execution logs and dbt `manifest.json` artifacts to map 5-layer end-to-end lineage. |

---

## 3. DESIGN-TIME WORKFLOW (AGENTIC SDLC)

Every new institutional ingestion pipeline is built autonomously through a 5-phase state machine with two mandatory human checkpoints:

```text
[1. Discovery] ──> [2. Assessment] ──(H1)──> [3. Blueprint] ──(H2)──> [4. Implement] ──> [5. Verify] ──> [PR Approved]
