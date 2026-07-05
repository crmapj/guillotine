# Guillotine — Foundation & Design

> **Guillotine, the headless accelerator.** An open-source generator that takes an API
> definition and emits a compact, typed **Python DSL** that LLM agents write *code*
> against — instead of calling a wall of verbose JSON tool schemas. It cuts token cost
> by 1–2 orders of magnitude in tool-heavy workflows and raises task success, by moving
> agent↔software interaction into the medium models are most fluent in: code.

**Status:** Design foundation for the Phase 0 OSS MVP implementation.
**Date:** 2026-06-28.
**License:** Apache-2.0 (vendor-neutral OSS).

This document is the research foundation and the architecture. It is written to be
shareable: it carries the *why* (evidence), the *what* (design), and the *how*
(roadmap), without internal positioning.

---

## 1. The thesis in one paragraph

Agents are far better at **writing code** than at **emitting tool-call JSON** — because
pretraining is saturated with real code and almost devoid of synthetic tool-call
formats. So the most efficient way to give an agent access to an API is not "N tools,
one per endpoint" but "one compact, typed code interface the agent composes against,
executed in a sandbox, returning only distilled results to the model." Guillotine
**generates that interface from a spec.** It is the missing compiler for the
"tools-as-code" era.

The one sentence that justifies the project:

> **Code-mode shrinks *what you load*; a DSL shrinks *what exists to load*. Guillotine does both.**

---

## 2. Why now — the evidence base

The "agents write code, not tool-calls" thesis went from idea to near-consensus in
~6 weeks of late 2025 and is now backed by both peer-reviewed research and production
numbers from multiple independent vendors.

| Source | Finding | Confidence |
|---|---|---|
| **CodeAct** (Wang et al., ICML 2024) | Code actions beat JSON tool-calls by **+20.7pp** success (74.4% vs 52.4%) and need **fewer turns** (5.5 vs 7.6) on the hardest multi-tool benchmark; win on **12/17** models | High — peer-reviewed |
| **Anthropic** — *Code execution with MCP* (Nov 2025) | Drive→Salesforce task: **150k → 2k tokens (98.7%)** | High, single scenario |
| **Cloudflare** — *Code Mode* (2025–26) | Entire 2,500-endpoint API (~1.17M tokens as MCP tools) → **~1k tokens** via 2 tools (99.9%) | High, single scenario |
| **Perplexity** — *Search as Code Generation* | CVE task: **288.7k → 42.9k tokens (85.1%)** at 100% accuracy; DSQA 0.871 vs OpenAI 0.733 | High |
| **Reference Python DSL** (see §4) | Real enterprise API: **~2.5–3× fewer tokens / ~2.2× fewer turns**, ties the equivalent CLI on correctness | High — de-contaminated benchmark |

**Why it works — three mechanisms:**
1. **Progressive disclosure** kills *static* schema bloat. You don't load N tool
   definitions up front; the agent discovers only what it needs.
2. **Data stays in the runtime.** Intermediate results live as variables in the
   sandbox and never round-trip through the model. The agent filters/aggregates
   *before* anything returns to context (this is where the 98% figures come from).
3. **Pretraining fluency.** Models write code in a language they already know far
   better than they emit a bespoke tool-call schema.

**Honest framing.** The 98.7% / 99.9% numbers are single, favourable, tool-heavy
scenarios. The defensible claim is *"1–2 orders of magnitude reduction in tool-heavy
workflows,"* not "always 99%." The reference-DSL **~2.5–3×** is the most honest
general figure because it comes from a mixed-hardness benchmark on a real API.

The structural cost to absorb (Anthropic's own stated trade-off): **running agent
code requires a secure sandbox.** Guillotine's runtime design (§6) absorbs it.

Key sources: [Anthropic — Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) ·
[Cloudflare — Code Mode](https://blog.cloudflare.com/code-mode/) ·
[Cloudflare — entire API in 1,000 tokens](https://blog.cloudflare.com/code-mode-mcp/) ·
[CodeAct (arXiv 2402.01030)](https://arxiv.org/abs/2402.01030) ·
[Perplexity — Search as Code Generation](https://research.perplexity.ai/articles/rethinking-search-as-code-generation).

---

## 3. The market gap — where Guillotine sits

Plotting every "API spec → interface" tool on two axes — **output form** (verbose
surface ↔ compact DSL) and **target** (human ↔ agent):

```
                      HUMAN-TARGETED                         AGENT-TARGETED
  VERBOSE   │ OpenAPI Generator, swagger-codegen,        │ OpenAPI→MCP generators
  (full     │ Speakeasy, Stainless, Fern, Kiota          │ (1 tool/endpoint) — the
  surface)  │ (SDKs);  Restish (CLIs)                    │ token hogs
            │                                            │
            │                                            │ Code-mode (Anthropic,
            │                                            │ Cloudflare, Stainless MCP):
            │                                            │ full SDK-as-code, shrunk by
            │                                            │ LAZY LOADING
  ──────────────────────────────────────────────────────────────────────────────────
  COMPACT   │  (nothing — humans want full SDKs)         │  ⬅ GUILLOTINE  ➡  EMPTY
  (designed │                                            │  Firetiger / CompText are
   DSL)     │                                            │  compact agent DSLs, but
            │                                            │  HAND-AUTHORED, not generated
```

**The empty cell is Guillotine's territory:** a generator that takes an API spec and
emits a **compact, *redesigned* DSL** purpose-built for agents, with guardrails
compiled in. Four things are unoccupied today:

1. **Generation, not hand-authoring.** Firetiger/CompText prove compact agent DSLs are
   token-efficient and enforce guardrails — but they're built by hand, per project.
2. **A DSL, not an SDK-as-code.** Code-mode (Anthropic, Cloudflare, Stainless MCP) is
   the strongest prior art and shares the "agents write code" thesis — but it emits a
   *full* SDK mirroring every endpoint 1:1, then relies on lazy loading. Guillotine
   distils the surface itself.
3. **Spec-agnostic & runtime-neutral.** Code-mode tools are MCP-coupled (Anthropic,
   Cloudflare) or SDK-coupled (Stainless). Guillotine goes straight from spec → DSL.
4. **Guardrails at the compiler level** — typed-choice enforcement, destructive-op
   tiers, and (the frontier, §5) silent-failure "landmine" guards.

**Closest precedent — the Google Workspace CLI.** It generates *both* a CLI and an Agent
Skills pack from API Discovery docs, regenerated in CI ("auto-generated … do not edit
manually"), with a layered skill model (service/helper skills from the command tree +
a shared template + persona/recipe TOML seeds). It validates the entire "spec →
interface **+ skills**, deterministically, zero-drift" discipline — but it is
**Workspace-specific** (hardcoded service registry, Discovery-API-coupled) and emits a
**CLI** (shell surface), not a distilled **DSL** (code surface) you can point at *any*
spec. Guillotine generalises the discipline and targets the code surface; its
skill-generation model (§5.4) is taken directly from this precedent.

**Positioning:** *the vendor-neutral compiler for the tools-as-code era — the
"Terraform of agent interfaces."* One spec in, portable agent-ready code **+ skills**
out, runs in any sandbox.

**Honest threats:**
- **Platform absorption** — Cloudflare and Anthropic are productising this natively.
  Guillotine must stay *more portable and spec-agnostic* than the platform versions.
- **"Tool search is good enough"** — Speakeasy showed ~100× reduction *without*
  code-mode via dynamic toolsets. Guillotine's answer: distillation (a smaller surface
  than any 1:1 map) + composition/control-flow in one call + compiled guardrails —
  things filtering alone can't provide.

---

## 4. The reference design — what a proven Python DSL teaches us

The architecture is not speculative. A production, verb-first **Python DSL over a real
enterprise API** (Dataiku's `dataikuapi`; the surrounding CLI is being open-sourced as
"Dataiku Headless") already implements this pattern and was benchmarked at **~2.5–3×
fewer tokens / ~2.2× fewer turns** against the equivalent CLI, tying it on correctness.
Guillotine generalises its shape. The canonical usage:

```python
import dku
p = dku.connect(project="RETAIL")

p.dataset("orders").set_types(amount="double").schema()
p.flow.join("orders", "customers", into="enriched",
            on="customer_id", how="LEFT").run().schema()
p.flow.group("orders", into="rev_by_region", by="region",
             agg={"amount": ["sum"]}).run().head(6)
p.flow.top_n("products", into="top5", by="unit_price", n=5, desc=True).run().head(6)

print(dku.cheatsheet(grep="join"))   # discover the surface on demand
print(dku.explain(p))                # orient before editing
```

### 4.1 The design properties worth copying

- **Verb-first, namespaced, fluent.** `connect() → project → .flow.<verb>() / .dataset()`,
  chaining `.run().head(n)`. One call per intent.
- **Uniform argument conventions.** Every verb takes `into=` (output), `where=`/`on=`,
  `describe=`, `name=`, `run=`. Keyword-only configuration.
- **Distillation built in.** `.head(n)` returns `list[dict]`, not a result object;
  build echoes `rows×cols` (the "grain", so a fan-out join can't pass silently);
  `analyze_column()` returns a curated flat dict, not the raw stats payload. Results
  are *deliberately* kept small — this is the token win.
- **Typed choices die early.** A bad enum value raises a teaching error with the valid
  set *before* the API call. "Make the illegal unrepresentable, loudly."
- **Errors teach.** Every error says what went wrong *and* the next action, so a model
  re-reading only the exception self-corrects in one turn.
- **`.raw` escape hatch on every handle** — the live underlying client, so the DSL
  never blocks the agent.
- **Idempotent `ensure_*` + replace-on-rerun** — after a mid-script failure, re-running
  the (fixed) script rebuilds cleanly. The script is the source of truth.
- **Self-generating discoverability.** `cheatsheet()` / `help()` / `help_json()` are
  built from live signatures + docstrings via `inspect`, so they *cannot drift*. The
  cheatsheet is scopeable (`section=`, `grep=`) to avoid a ~14k-token full dump —
  progressive disclosure, for free.
- **Destructive-op speed-bump.** `delete`/cascade ops route through a tiered `guard()`
  that *raises* a typed, interceptable signal (not `sys.exit`) — forces explicit
  destructive intent and gives a harness a hook.

### 4.2 The most important finding — generatable vs hand-crafted

The reference DSL decomposes cleanly into two layers. **This boundary defines what
Guillotine's generator does automatically vs what needs an LLM-assisted authoring pass.**

**MECHANICAL — auto-generatable from a spec (~70–80% of LOC, and the most
error-prone-to-hand-write parts):**

| Artifact | Generated from |
|---|---|
| Verb / method stubs | one per operation |
| Enum guard tuples + early-death checks | every enum / `Choice` field in the spec |
| Namespacing into handles/mixins | resource tags → classes |
| Typed signatures, required-vs-optional, kwargs-only | schema field types & requiredness |
| **The entire discoverability layer** (cheatsheet/help/help_json) | free — pure `inspect` over generated code |
| `.raw` escape hatch | boilerplate per handle |
| Lifecycle scaffolding (the recipe-factory chokepoint, collision handling, build/poll) | template |
| Destructive-op safety tiers | HTTP verb → tier (DELETE/CASCADE) |
| `ensure_*` idempotent constructors | template per create-op |

**HAND-CRAFTED — the 20–30% that is the actual value, and cannot come from a static
spec (the generator's LLM-assisted "fill-in-the-blanks"):**

| Artifact | Why a spec can't produce it |
|---|---|
| **Result distillation** (which fields `head`/`info` show; the "grain" echo) | judgment about what a model needs to *see* |
| **Ergonomic helper verbs** (`top_n`, `split`, `distinct`) | compose/specialise raw ops into agent-intent verbs |
| **String-arg grammars** (`on="l>=r"`, `where=` expressions) | the ergonomic argument language |
| **"Landmine" guards** (e.g. a type-relabel that silently NULLs data) | encode *empirical* silent failures — discoverable only by live testing |
| **"Footgun" field-name encoding** | knowledge of where the model's priors are *wrong* |
| **Error next-action prose** | the teaching layer; specs give codes, not remediation |
| **Scope curation** (which subset is agent-useful) | a product judgment |

> **The crisp boundary:** a generator can mechanically emit the skeleton + guards +
> discoverability + lifecycle + safety tiers. What needs an LLM-assisted pass *informed
> by live API behaviour* (not the static spec) is the ergonomic verb layer, the result
> distillation, and the landmine/footgun guards. **The discoverability layer in
> particular is *better* generated than hand-written** — it's pure introspection.

---

## 5. Architecture

Guillotine has three parts: a **Compiler** (spec → DSL), a headless **Runtime**
(execute + distil), and the **Landmine Loop** (the frontier feature that produces the
high-value guards a static spec can't).

```
 INPUT                        ┌──────────────────────────────────────────────┐
 • OpenAPI 3 (first)          │  COMPILER                                      │
 • GraphQL / gRPC (later)     │  1. Ingest + normalize/repair                  │
 • existing SDK via           │     (synth missing operationIds, summarize     │
 •   reflection ──────────────►     bloated schemas)                           │
   (e.g. a Python client)     │  2. Build CURATED CORE IR                      │
                              │     resources · operations · enums · types ·   │
                              │     auth · pagination · error shapes ·         │
                              │     destructive-tiering                         │
                              │  3a. MECHANICAL EMIT  (the ~75%)               │
                              │     handles/mixins · verb stubs · enum guards · │
                              │     typed sigs · ensure_* · .raw · _make        │
                              │     factory · safety tiers · the WHOLE          │
                              │     discoverability layer (inspect-based)       │
                              │  3b. LLM-ASSISTED AUTHORING  (the ~25%)        │
                              │     ergonomic helper verbs · string-arg         │
                              │     grammars · result distillation · teaching   │
                              │     error prose                                 │
                              │  3c. LANDMINE LOOP  ◄── the frontier (§5.1)    │
                              │  4. EMIT: (a) Python DSL package                │
                              │          (b) generated Skill/manifest           │
                              │          (c) optional grammar (open models)     │
                              │          (d) runtime adapter                    │
                              └───────────────────────┬──────────────────────┘
                                                      │ generated DSL package
   AGENT writes code  ───────►  ┌──────────────────────────────────────────────┐
   against the DSL              │  HEADLESS RUNTIME  ("the accelerator")         │
   (sees ~1k tokens)            │  • sandboxed exec (Pyodide/Deno · or locked-   │
                                │    down subprocess · pluggable)                │
                                │  • DSL is the ONLY egress; auth resolver       │
                                │    chain; secrets in supervisor, never in      │
   only distilled result ◄──────│    context or sandbox                          │
   back to context              │  • result distillation: only returned/         │
                                │    logged data re-enters context               │
                                │  • ships as MCP server: ONE exec code-mode     │
                                │    tool (mirrors the reference `dku_exec`)     │
                                └────────────────────────────────────────────────┘
```

### 5.1 The Landmine Loop (the defensible frontier)

This is what makes Guillotine more than a codegen tool. The highest-value guards —
the ones that catch *silent* failures ("exit 0 ≠ success": the API accepts a wrong
field as a no-op, a type relabel quietly NULLs data) — **cannot be derived from a
static spec.** The reference DSL discovered them only through live testing.

So Guillotine includes an optional **live-probe harness**: spin the generated DSL in a
sandbox against a real or mocked instance, have an LLM exercise each verb, detect
exit-0-but-wrong outcomes and places where the model's priors misfire, and emit the
corresponding **landmine guards + footgun field-name encodings + teaching errors**.
This closes the loop from "generate the skeleton" to "generate the *valuable* guards,"
and it is the genuinely novel research contribution.

### 5.2 Input modes

- **OpenAPI 3** — the primary path (operations → verbs, schemas → types, enums →
  guards, tags → namespaces, security schemes → auth, HTTP verbs → safety tiers).
- **Existing SDK via reflection** — introspect a client library's methods/signatures
  directly (this is exactly how the reference DSL wraps `dataikuapi`). Lets Guillotine
  target APIs whose best "spec" is their client.
- **GraphQL / gRPC** — later.

### 5.3 The "one surface, N projections" principle

The reference work crystallised a reusable idea: **the same curated core can be
projected into multiple clothes, chosen by where the agent's code runs** — a CLI
(outside the host, any shell), an in-process DSL (`import`), and an MCP projection
(governed tool-callers). Guillotine's Curated Core IR (step 2) is designed to support
exactly this: the Python DSL is projection #1; CLI and MCP projections fall out of the
same IR later.

### 5.4 Skill generation — the documentation projection (deterministic)

A generated DSL is not in pretraining, so it needs in-context teaching to land
(Perplexity: a custom SDK "requires highly-tuned Agent Skills"; the reference DSL ships
a `dku-py` skill). The sharp question is **how much of that skill can be
*deterministic*?** The Google Workspace CLI answers it in production: its skills are
auto-generated (`gws generate-skills`, regenerated in CI via `generate-skills.yml`,
header: *"Auto-generated … Do not edit manually"*), in a **layered hybrid** model.
Guillotine adopts the same model, sourced from the Curated Core IR (§5.2):

| Skill tier | Source (Google → Guillotine) | Determinism |
|---|---|---|
| **Service / module** | Discovery doc + command tree → spec resources/tags + IR | 100% from spec; one skill per DSL namespace |
| **Verb / operation** | clap subcommand + doc-comments → DSL introspection (`help_json`) + spec descriptions | Deterministic — *the same `cheatsheet/help` data, rendered as SKILL.md* |
| **Shared / foundational** | hardcoded `gws-shared` template → Guillotine runtime contract | Template: auth, `.raw` escape hatch, result distillation, sandbox conventions |
| **Gotchas / warnings** | hand-authored "Tips" prose → **Landmine Loop** (§5.1) | Google authors these; Guillotine *discovers* them by live probing |
| **Recipe / persona (workflows)** | `personas.toml` / `recipes.toml` seed → templated render | Hybrid: compact authored seed `{name, goal, services, steps[], caution}` → deterministic expansion |

**The principle: a skill is just another projection of the Curated Core IR (§5.3) — the
*documentation* projection, the static twin of the runtime `cheatsheet()/help()`
surface.** Same fact, two delivery modes: the skill is *pre-loaded, host-level*
progressive disclosure; the cheatsheet is *on-demand, in-runtime* progressive
disclosure. Both regenerate from one source, so neither drifts. One source even feeds
*four* outputs by construction: the safety tier that arms a DSL guard also emits the
skill's write-warning, the CLI's `--yes` speed-bump, and the MCP annotation.

**The "authored" layer is structured data, not prose.** Google's workflow skills are
~8 lines of TOML each; the generator renders the full, cross-linked SKILL.md (incl. a
`requires: [skill-a, skill-b]` dependency graph). So even the 20–30% stays regenerable
and consistent — a human (or an LLM bootstrap pass) writes the seed, the pipeline writes
the skill.

**Three places Guillotine goes beyond the Google model:**
1. **Probe-sourced gotchas.** Google hand-writes the domain "Tips" (the part schema
   introspection can't give). Guillotine's Landmine Loop discovers silent-failure
   warnings by live testing and emits them — the highest-value skill content, generated.
2. **Probe-validated examples.** Google's examples are hand-written and can rot.
   Guillotine generates candidate examples, *runs them in the sandbox, and ships only the
   ones that execute* — self-verifying skill content.
3. **Single-IR consistency.** DSL, CLI, MCP, and skills all fall out of one IR, so they
   cannot disagree — the drift that plagues hand-maintained docs is structurally absent.

**Output target:** portable **Anthropic Agent Skills** format (a `SKILL.md` per skill
with `name` + a concise `description` trigger + progressive-disclosure `references/`),
so it loads in Claude Code and any compatible host — plus a generated index page
(à la `docs/skills.md`). Curation/exclusion is explicit (Google's `BLOCKED_METHODS`
const → a Guillotine scope filter), and descriptions are length-bounded for the trigger
field.

---

## 6. Runtime & security design

> **Implementation status (read this first).** This section is the *design target*,
> not what v0 ships. The v0 executor (`guillotine.runtime.execute`) is a plain
> subprocess with **no isolation**: agent code runs with the full privileges of the
> calling user (filesystem, network, subprocesses). It enforces a timeout (process-group
> kill) and withholds non-prefixed host env vars from the child, and the generated `exec`
> MCP tool is disabled until `GUILLOTINE_ALLOW_EXEC=1` — but it is **not** a sandbox, the
> DSL is **not** the only egress, and secret-isolation is **not** implemented. The bullets
> below describe the hardened executor that hosted use requires (Phase 1). See
> [`docs/security-model.md`](docs/security-model.md) for the current boundary.

Drawn directly from the Anthropic / Cloudflare reference architectures and the
reference DSL's auth model:

- **The DSL is the only door.** No ambient network in the sandbox; the generated
  wrappers are the sole capability surface.
- **Secrets live in a supervisor, never in context or the sandbox.** Auth resolves via
  a chain (explicit args → env → keychain profile → injected in-host ticket). The agent
  never sees a credential — which neutralises prompt-injection-to-credential-theft.
- **Pluggable executor.** Python-first: Pyodide/Deno WASM or a locked-down subprocess
  for the embedded/library case; microVM (Firecracker/E2B) or gVisor for hardened
  multi-tenant hosting. Don't hard-wire one.
- **Result distillation is the token win.** Filtering/aggregation happens in the
  sandbox; only `return`ed/`log`ged data re-enters context. Large blobs go to an
  artifact store and return a pointer + summary.
- **Generated wrappers are pagination-aware, error-typed, and filter-before-return** —
  this is Guillotine's concrete edge over hand-written MCP tools (it can encode the
  page-exhaustion loop and the error/partial-result schemas agents otherwise loop on).
- **Ship as an MCP server with a single `exec` code-mode tool** (mirrors the reference
  `dku_exec`) → instant plug-in to Claude Code, Cursor, etc. at a ~1k-token footprint,
  while keeping the MCP surface tiny.

---

## 7. Decisions locked (2026-06-28)

| Decision | Choice | Rationale |
|---|---|---|
| **DSL form** | **Embedded Python DSL** (like the reference `dku` DSL) — distilled typed library, not a novel grammar | Maximal pretraining fluency; the reference proves the shape works and is benchmarkable |
| **Dataiku coupling** | **Vendor-neutral, Dataiku-stewarded** | Maximise adoption + credibility; the reference DSL is the proof point, not a dependency |
| **Host language** | **Python-first** | Aligns with the reference, the data ecosystem, and Perplexity's choice; best in-sandbox data-wrangling |
| **v1 scope** | **Generator (DSL + skill pack) + thin runtime + MCP server** | End-to-end story; launch-ready; skills are near-free off the same IR; the MCP wrap is the cheapest path into agent clients |

**Grammar / external DSL:** reserved as an *optional* layer (constrained decoding for
open-weight/local models via GBNF/XGrammar; hard safety boundaries) — not the core.

---

## 8. Naming note (actionable, not a blocker)

"Guillotine / headless accelerator" is a coherent metaphor (cut off the verbose "head"
of tool schemas; it slots into the "Dataiku Headless" family). Caveats: `guillotine` is
**taken on both npm and PyPI**, it's a generic term in 2D bin-packing (CS), and "an AI
that decapitates" is a faintly dark connotation. No notable *AI/agent* project owns it,
so that mindshare is open. Decision: kept, with the package namespace scoped as
`guillotine-gen` and messaging leaning into "clean cut / removes bloat."

---

## 9. Roadmap

**Phase 0 — MVP (the publishable proof).** One command — `guillotine build <spec>` —
emits the DSL + skill pack + MCP server from a single IR, so they cannot drift.
1. **OpenAPI 3 → distilled Python DSL** — real distillation pass (CRUD collapse,
   auth/pagination hiding, tag namespacing) + the auto-generated `cheatsheet/help`
   discoverability layer.
2. **Generated Agent Skills pack** (first-class output, §5.4) — service + verb + shared
   + recipe tiers in portable `SKILL.md` format + an index page, off the same IR.
   Near-free once the IR exists, and a strong standalone demo: *"any OpenAPI spec → a DSL
   **and** a drift-free skill pack."*
3. **Thin Python sandbox runtime** that executes agent code against the DSL and distils
   results.
4. **MCP server wrapper** (single `exec` tool).
5. **Benchmark harness** — token cost + task success vs (a) raw OpenAPI→MCP and
   (b) code-mode, on 2–3 real APIs (e.g. GitHub, Stripe, a Dataiku API). **Publish the
   numbers — that is the launch.**

**Phase 1 — the Landmine Loop.** Live-probe harness that discovers silent-failure
guards and emits them — feeding *both* the DSL guards **and** the skill pack's gotcha
tier — plus **probe-validated examples** (generate candidate examples, run them in the
sandbox, ship only those that execute, so skill examples can't rot). This is the
differentiator; ship it once the MVP proves the mechanical path.

**Phase 2 — breadth.** GraphQL/gRPC input; SDK-reflection input; the CLI and MCP
projections from the same Curated Core IR; optional grammar emission for open models.

**Dogfood milestone (validation, any phase):** regenerate the *mechanical* 70–80% of
the reference `dku` DSL from `dataikuapi` (via SDK reflection) or the DSS REST spec —
a clean proof that the generator reproduces a hand-built, benchmarked DSL.

---

## 10. Open questions

- **Distillation autonomy.** How much of the "which fields to show / which verbs to
  collapse" can an LLM authoring pass decide well unsupervised vs needing a human review
  gate? (Determines how hands-off the generator can be.)
- **Landmine Loop cost.** Live-probing is expensive and needs a real/mocked instance.
  What's the minimum probe set that finds the high-value traps?
- **Spec quality floor.** Generated quality is bounded by spec quality. How much
  "spec repair" (synthesising names, summarising schemas) is needed before the output
  is usable? Most real OpenAPI specs are imperfect.
- **Grammar payoff.** Is emitting a constrained-decoding grammar worth it for the
  open-model segment, or does the host type-checker + repair-turn cover it?
- **Recipe-seed bootstrapping.** Recipe/persona skills need authored seeds. Can an LLM
  pass propose good candidate recipes from common operation sequences (then a human
  curates), so even the seed authoring is assisted rather than fully manual?
- **Skill-format portability.** Anthropic Agent Skills (`SKILL.md`) is the canonical
  output; do we also emit adapters for other hosts' skill/manifest formats, or stay
  single-format and rely on its portability?
- **Naming.** Keep "Guillotine" (and secure namespaces) or pick a non-colliding mark?

---

## 11. Sources

**Theory / evidence**
- [Anthropic — Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Anthropic — Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Cloudflare — Code Mode](https://blog.cloudflare.com/code-mode/) · [entire API in 1,000 tokens](https://blog.cloudflare.com/code-mode-mcp/)
- [CodeAct — arXiv 2402.01030](https://arxiv.org/abs/2402.01030) · [HTML w/ tables](https://arxiv.org/html/2402.01030v4)
- [Voyager — arXiv 2305.16291](https://arxiv.org/abs/2305.16291)
- [Hugging Face — smolagents (code agents)](https://huggingface.co/docs/smolagents/en/conceptual_guides/intro_agents)
- [Perplexity — Search as Code Generation](https://research.perplexity.ai/articles/rethinking-search-as-code-generation)

**Prior art / landscape**
- [OpenAPI Generator](https://github.com/OpenAPITools/openapi-generator) · [Stainless](https://www.stainless.com/) · [Speakeasy](https://www.speakeasy.com/) · [Fern](https://buildwithfern.com/) · [Kiota](https://github.com/microsoft/kiota)
- [Restish (OpenAPI→CLI)](https://github.com/danielgtaylor/openapi-cli-generator) · [OnlyCLI — CLI-vs-MCP token benchmark](https://onlycli.github.io/OnlyCLI/blog/mcp-token-cost-benchmark/)
- [Stainless MCP](https://www.stainless.com/docs/mcp/) · [Speakeasy — 100× via dynamic toolsets](https://www.speakeasy.com/blog/how-we-reduced-token-usage-by-100x-dynamic-toolsets-v2)
- [Firetiger — custom languages for agents](https://blog.firetiger.com/custom-programming-languages-make-agents-really-really-smart/)
- [ramhaidar/Code-Executor-MCP](https://github.com/ramhaidar/Code-Executor-MCP) (closest code-mode, MCP-only, nascent)
- [Google Workspace CLI — skills docs](https://github.com/googleworkspace/cli/blob/main/docs/skills.md) · [generate_skills.rs (the generator)](https://github.com/googleworkspace/cli/blob/main/crates/google-workspace-cli/src/generate_skills.rs) — the blueprint for deterministic, CI-regenerated skill generation (§5.4)

**DSL generation / constrained decoding**
- [Grammar Prompting (arXiv 2305.19234)](https://arxiv.org/abs/2305.19234)
- [Survey: LLM codegen for low-resource/DSLs (arXiv 2410.03981)](https://arxiv.org/pdf/2410.03981)
- [XGrammar (arXiv 2411.15100)](https://arxiv.org/pdf/2411.15100) · [Grammar-Aligned Decoding (arXiv 2405.21047)](https://arxiv.org/html/2405.21047v3)

**Runtime / sandboxing**
- [Anthropic — Claude Code sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)
- [langchain-ai/langchain-sandbox](https://github.com/langchain-ai/langchain-sandbox) · [pydantic/mcp-run-python](https://github.com/pydantic/mcp-run-python)
- [@cloudflare/codemode (npm)](https://www.npmjs.com/package/@cloudflare/codemode)

**Reference implementation:** the `dku` Python DSL (`src/dku/` in the dataiku-cli repo,
`dsl/course-correction-recovery` branch) — the proven, benchmarked shape Guillotine
generalises.
