# HydroMAS Skill Repository: Architecture Audit and Development Roadmap

## 1) Current Architecture and Module Structure

### Repository scope
This repository is a **HydroMAS OpenClaw skill wrapper** focused on CLI-side orchestration, not the core HydroMAS backend itself.

### Top-level structure
- `SKILL.md`: user-facing skill entrypoint and usage guide for HydroMAS capabilities.
- `scripts/hydromas_call.py` (~4,003 lines): primary CLI application and orchestration layer.
- `scripts/llm_client.py`: lightweight LLM client abstraction (DashScope-compatible OpenAI API).
- `scripts/hydromas_evolve.sh`: bridge script for EvoMap evolution workflows.
- `scripts/codex_hydromas_audit.sh`: helper to run Codex-based audit workflows against the external HydroMAS repo.

### Runtime architecture (as implemented here)
- User command -> `hydromas_call.py` subcommand dispatch
- `hydromas_call.py` routes to HydroMAS HTTP APIs (gateway/skill/chat/report/chart/etc.)
- Optional publishing to Feishu Doc API (document creation, block rendering, image upload, ACL)
- Optional LLM usage for intent classification and role-specific interpretation
- Optional EvoMap operations via subprocess calls to external `evolver` directory

### Internal module boundaries inside `hydromas_call.py`
- Transport utilities: `_get`, `_post`, `_post_binary`, `_api_headers`
- Formatting/rendering: `_format_result`, `_render_dict_to_md`, `_build_adaptive_report`, markdown-to-Feishu block conversion
- Context model: role/case inference, session load/save, natural-language param parsing
- Routing and execution: `cmd_chat`, `cmd_report`, `cmd_full_report`, `cmd_api`, `cmd_evolve`, etc.
- Feishu integration: token management, block/table/image APIs, publish and grant flows
- Skill catalogs/defaults: large static dictionaries for API wrappers and scenario defaults

## 2) Technical Debt and Structural Risks

### Critical (addressed in this iteration)
1. **Hardcoded secrets / credential defaults in source**
- Previous code embedded fallback keys/secrets for LLM and Feishu.
- Risk: credential leakage, accidental production misuse, audit/compliance failure.

### High
2. **Monolithic core file (`hydromas_call.py`)**
- ~4k LOC single-file coupling of CLI parsing, routing, business rules, HTTP clients, rendering, and integrations.
- Risk: high change failure rate, hard review/testing, unclear ownership boundaries.

3. **No automated test suite in this repository**
- No unit tests around context parsing, routing logic, report rendering, or API wrapper merge behavior.
- Risk: regressions on routine edits; no confidence gate.

4. **Tight coupling to absolute paths and external runtime assumptions**
- Hard references to `/home/admin/hydromas`, `/home/admin/evolver`, session/report data paths.
- Risk: brittle portability and difficult local/dev/prod parity.

### Medium
5. **Large static default payloads and config embedded in code**
- API defaults and profile data are inline constants.
- Risk: noisy diffs, update friction, impossible to validate schema externally.

6. **Inconsistent error model across external APIs**
- Mixture of top-level and nested error checks with partial fallback paths.
- Risk: silent degraded behavior and debugging overhead.

7. **Checked-in transient artifacts (`scripts/__pycache__/`)**
- Risk: repository hygiene issues and noisy changes.

## 3) Concrete Next-Phase Development Roadmap

### Short term (1-2 weeks)
1. Complete credential hardening and docs
- Keep all external credentials env-only, with explicit preflight checks and failure messages.
- Add `.env.example` with required variables.

2. Extract core modules from `hydromas_call.py`
- `transport.py`, `context.py`, `feishu_client.py`, `reporting.py`, `commands/` package.
- Preserve CLI behavior exactly while reducing coupling.

3. Add baseline tests and CI
- Unit tests for context resolution and parameter parsing.
- Snapshot-style tests for report rendering paths.
- Add CI job: lint + test + py_compile.

### Mid term (1-2 months)
1. Externalize configuration and defaults
- Move case profiles, API skill defaults, and labels to versioned JSON/YAML config files.
- Add schema validation on load.

2. Standardize error handling and telemetry
- Unified response wrapper and structured logs.
- Add trace IDs for API calls and publish operations.

3. Improve portability
- Replace hardcoded absolute paths with env/config-driven paths and sane relative defaults.

### Long term (1-2 quarters)
1. Plugin-based command architecture
- Each command group as isolated module/plugin with clear contracts.

2. Reliability engineering
- Retries/backoff policies standardized; timeout budgets per endpoint.
- Add end-to-end smoke tests against a mocked/staging HydroMAS API.

3. Governance and release quality
- Semantic versioning, changelog discipline, and upgrade notes for command behavior changes.

## 4) First Iteration Implemented Now (Highest Priority)

### Improvement implemented
**Security hardening: removed hardcoded credentials and enforced env-based credential configuration.**

### Code changes completed
- `scripts/llm_client.py`
  - Removed embedded fallback API key.
  - LLM API key now strictly from `HYDROMAS_LLM_API_KEY` or `DASHSCOPE_API_KEY`.
  - CLI debug output now handles missing key safely.
- `scripts/hydromas_call.py`
  - Removed hardcoded Feishu app ID/secret and default openid values.
  - Added `_validate_feishu_credentials()` preflight check.
  - `_feishu_token()` now fails fast with explicit env-var guidance when credentials are missing.
  - Permission grant logic now skips admin grant when `FEISHU_DEFAULT_OPENID` is unset.
  - `FEISHU_DOC_DOMAIN` now defaults to neutral `open.feishu.cn`.

### Why this was first
This is a high-severity, low-risk, immediate-value fix that reduces security exposure without changing core business logic.

## 5) Immediate Next Implementation Target
After this security patch, the next highest-value implementation is:
1. Break `hydromas_call.py` into modular packages while preserving current CLI contracts.
2. Add unit tests for `_resolve_context`, `_parse_user_params`, and report rendering fallbacks.
