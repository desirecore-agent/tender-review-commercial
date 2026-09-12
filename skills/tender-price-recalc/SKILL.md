---
name: tender-price-recalc
version: "0.2.0"
description: Find material calculation errors and incompatible pricing bases, with reproducible explanations.
---

# Commercial price review

## Outcome and acceptance

Find material calculation errors and incompatible pricing bases, with reproducible explanations.

**Good:** Preserve declared values; show independently calculated values, formulas and differences. Establish units, currency, tax basis and rounding from sources. Distinguish arithmetic error from unresolved basis, explain the effect and a usable correction or clarification.

**Not good:** Reporting only a total; silently assuming tax inclusion or conversion rates; changing original values to match calculations; inferring the cause from a difference; calling every discrepancy a rejected bid.

**Example:** A source lists 3 units at 0.1 currency units each and declares 0.4. Show 3 × 0.1 = 0.3 and a 0.1 discrepancy, cite the row and applicable correction clause; do not invent a rounding explanation.

Assess material omissions, false positives, source-location correctness and actionability. These are quality criteria, not a quota of findings. A clean result needs an explanation of what was examined; an incomplete result identifies the exact gap and its effect. No accuracy percentage is claimed without an evaluated sample set.

## Assignment and delivery

Accept a clear natural-language assignment describing background, objective, available materials, authorized scope, quality expectations and delivery destination. Choose reading order, tools and presentation autonomously. Ask only about ambiguities that change the answer; continue independent checks with available material. No business input schema, metadata preflight or runtime receipt is required to begin.

Deliver a usable professional conclusion, supporting locations, recommended actions and remaining limitations. Markdown, a table, a direct substantive reply or requested files are all valid; no fixed file count or six-artifact pack is required. If a file is requested, create it and check it is readable before reporting delivery. Reading and planning alone are not completion. On interruption, continue from usable work, identify gaps and deliver the completed portion honestly. For targeted rework, answer the specific concern and explain any changed conclusion. The lead accepts the substantive work; independent Evidence review is not self-certified.

## Optional tool reference below

Select the following methods as needed for the materials and conclusion. A calculation or measurement script's input/output constraints apply only when that script is used; every business task need not execute every tool. Check the actual capabilities and dependencies needed by the chosen method.

## Purpose

Perform **reproducible** numerical verification of bid/tender prices: every calculation step preserves the input value, unit, currency, tax basis, formula (`expression`), rounding rule, and result, so that anyone can re-run the same calculation with the same inputs and obtain the same output.

Supported operations:

- Amount summation (`sum`)
- Quantity × unit price totals (`multiply`, with multi-line summary verification)
- Unit conversion (`convert_unit`, wan_yuan ↔ yuan)
- Rounding to a specified rule (`round`, e.g., `ROUND_HALF_UP` to fen, `ROUND_05UP` at 0.05 steps)

## Core Principles (violation = rejection)

1. **Exact decimal**: Amounts are parsed into precise integer triples (sign × coefficient × 10^exponent). Addition, multiplication, and division by 10000 are all completed in the integer domain with exact precision; no binary floating-point is used, no global precision context is relied upon, and there is no intermediate rounding, overflow, underflow, or normalization loss. `0.1 + 0.2` is exactly `0.3`.
2. **Contract-enforced validation**: Each operation is validated against `schemas/input.schema.json` for allowed fields, required fields, types, arrays, and nested structures; **unknown fields are always rejected** (e.g., `sum` carrying `unit`, or line-level `tax_basis` — the caller must unify the basis and resubmit). Amounts must be **string-formatted** decimal numbers; JSON integer/float/boolean amounts are rejected; `rounding`, if present, must be an object; `rounding: null` is rejected.
3. **Uncertain basis → pause, never guess**: `currency` must be a known ISO code; `tax_basis` must be a known value; comparisons across different currencies/bases/units pause and report the uncertainty — no mixed calculations allowed.
4. **Null is never zero**: Missing amount ≠ amount is 0. null, missing fields, and empty strings are all rejected.
5. **Finite numbers only, with explicit limits**: NaN, Infinity, -Infinity are rejected; numeric string length (≤128 chars), significant digits (≤64), exponent (±500), operand/line count (≤1000), and output text length (≤128 KiB) have explicit upper bounds; exceeding bounds triggers structured rejection — finite non-zero numbers are never silently treated as zero.
6. **No expression execution**: The script never evaluates input as code (`eval`/`exec`/`compile` are prohibited). All "formulas" are assembled by the script by operation type and recorded verbatim in the output's `expression` field.
7. **No modification of originals; exclusive output creation**: The script only reads input files. Output may only be written to **non-existent** paths: identity and collision pre-validation (canonical path + device/inode detection, covering same path, symlinks, and hardlinks) is followed by exclusive creation (`O_CREAT|O_EXCL`); existing regular files, symlinks, directories, and input=output are all rejected. Output path or exclusive creation failure writes no file; data validation rejection on an admitted target may still produce rejected JSON on stdout — preserve and check stdout, stderr, and the real exit code.
8. **Echo preserves original inputs**: Output `inputs` echo the exact strings provided by the caller (preserved verbatim); formulas and result values are computed separately and precisely; no lossy normalization dependent on precision context.
9. **No auto-correction, no policy discount calculation**: The tool only outputs recalculation results and candidate corrections; evaluation prices and policy discounts are outside its scope; calculation errors do not automatically equal invalidity.

## Overwrite Policy (explicit)

- **Never overwrite** any existing output file (regular file, symlink, or directory); outputs pointing through symlinks to other locations are also rejected.
- To re-run the same calculation: use a new output path; or have the caller delete the old output first. **Re-run semantics are controlled by the caller, not the script.**
- Identical paths (`--input` and `--output` same or mutually hardlinked/symlink-resolved) are always rejected to prevent truncating the input file; the same validation applies to rejected inputs.
- On mid-write failure, the half-written file is removed; exit code 3.

## Usage

Script location: `scripts/recalc.py` (Python standard library only, Python ≥ 3.8).

```bash
python3 scripts/recalc.py --input <input.json> [--output <output.json>]
```

- Without `--output`, the result JSON is printed to stdout.
- Exit codes: `0` success; `2` input rejected (contract violation, unknown field, unknown currency/basis, null value, non-finite number, unparseable, exceeds limits, etc.); `3` usage/IO error (input unreadable, output path security validation failed, exclusive creation failed).
- **Never infer JSON availability from the exit code alone.** Calculation or reportable input validation may produce structured JSON on stdout; however, argument parsing errors, output-size limit violations, file I/O failures, and refused output paths may produce stderr only. Empty or unparsable stdout is not a pass — callers must always check the actual exit code.
- With a valid `--output` target: input validation failure (exit code 2) may write rejected JSON to the output file; a refused output target (exit code 3) writes no file.
- Callers must preserve raw stdout, stderr, and the real exit code for each step to maintain a complete audit trail.

### Input Format (see `schemas/input.schema.json`)

Common fields:

| Field | Required | Description |
|---|---|---|
| `operation` | Yes | `sum` / `multiply` / `convert_unit` / `round` |
| `currency` | Yes | ISO 4217 three-letter currency code. Known set: CNY, USD, EUR, JPY, GBP, HKD |
| `tax_basis` | Yes | Tax basis: `tax_inclusive` (tax included) / `tax_exclusive` (tax excluded) / `not_applicable` |
| `rounding` | No (`round` required) | `{ "mode", "increment" }`; mode is one of 8 rounding mode names; increment is a positive decimal string (e.g., `"0.01"` for fen, `"1"` for yuan). Value of `null` is rejected; omitting entirely means no rounding |

Operation-specific fields:

- `sum`: `operands` — array of amount strings (1–1000 items).
- `multiply`: `line_items` — array of `{ quantity, unit_price }` (1–1000 lines); line-level `quantity × unit_price` is computed per line, then summed. Only these two keys are allowed per line.
- `convert_unit`: `amount` + `from_unit` + `to_unit` (yuan ↔ wan_yuan; must differ).
- `round`: `amount` (unrounded value).

All amounts must be **strings** (e.g., `"1234.56"`) to avoid binary floating-point distortion; JSON integer/float/boolean amounts are rejected. Any key beyond operation payload and common fields (including line-level tax basis fields that may conflict with the top-level basis) is rejected — resolve conflicts at the caller level first.

### Numeric Limits (explicit, explainable)

| Limit | Upper Bound | Exceeding Behavior |
|---|---|---|
| Single numeric string length | 128 characters | Structured rejection |
| Single numeric significant digits | 64 digits | Structured rejection |
| Decimal exponent | ±500 | Structured rejection (finite non-zero numbers are never silently zeroed) |
| `sum.operands` item count / `multiply.line_items` line count | 1000 | Structured rejection |
| Output JSON text length | 128 KiB | Rejection (exit code 2/3) |

### Output Format (see `schemas/output.schema.json`)

On success: `status: "ok"` with `expression` (human-readable formula), `inputs` (echo: **amounts preserve caller's original strings**), `result` (with `value`, `unit`, `currency`, `tax_basis`, `rounded`), `rounding` (applied or not), `warnings`.

On rejection: `status: "rejected"` with `errors`; no numerical results given.

### Basis Registration Table

Before comparing multiple amounts, register each item's currency, unit, tax basis, and rounding convention using the template in the *Rounding & Basis Reference* (see `舍入与口径说明.md` for Chinese or `Basis-Reference.en.md` for English). Comparisons pause if the registration is incomplete.

## Integration with Bid Review Workflow

- When the recalculated value differs from the bid document value: record both values and the formula, provide a **candidate correction**, and note "whether this constitutes a correction depends on the tender document's correction rules"; invalidity is never declared.
- Amount mismatch between figures and words: similarly record both values and the difference, and defer to the tender document's correction rules.
- Policy evaluation discounts (SME, domestic product, etc.): **never** compute from scratch with this tool; if the project explicitly provides the rate and stacking conditions, compute manually/separately, and the evaluation price does not replace the bid price.
- Candidate recalculation is conditional on the listed unit prices and tender quantities; the agent does not autonomously correct pricing for the purchaser or judge bid validity.

## Caller & Reporting General Rules

> These rules apply to any review round using this skill, independent of specific project paths or sample answers.

### Preserve Original Declared Values

- When the user declares specific values (amounts, tax amounts, totals), record them verbatim as **declared values**.
- Perform independent recalculation using the tool. Record the recalc result separately as **recalc values**.
- Compute and record the **difference** between declared and recalc values.
- **Never modify user-declared values to match recalc results** — the declared values are immutable facts from the source document.

### No Reverse-Engineering from Differences

- When a discrepancy is found between declared and recalculated values, report the discrepancy factually: declared value, recalc value, and the numeric difference.
- **Do not reverse-engineer the cause** (e.g., "rounding error", "data entry error", "tax calculation mistake") unless the evidence directly and uniquely supports that specific conclusion.
- If the cause is uncertain, state "cause undetermined — further investigation needed" (原因待核).

### Output Location

- All user reports, calculation intermediates, and test outputs must be written to the **output directory explicitly specified by the user** in the current request.
- Do not write to the Agent's own source directories (agent root, skills/, etc.) unless explicitly instructed.

### Complete Command Audit Trail

- For every `recalc.py` invocation, save and preserve: (1) the exact input JSON file, (2) the complete stdout, (3) the complete stderr, (4) the real exit code.
- Exit codes must be captured from the actual command return value — never mask with `|| true` or discard.
- Stderr must never be redirected to `/dev/null` or otherwise discarded.
- Failed commands must also be recorded with their actual exit code and stderr. Do not retroactively mark failed invocations as exit 0.
- Each invocation must have a unique input file and a unique output file path. Reuse of existing output paths may trigger exit code 3 (exclusive creation failure) — this must be recorded, not hidden.

### Result Semantics & Basis Consistency

- The script's `tax_basis` field is a faithful echo of the caller's input; the script itself does not change its semantics. The caller must pass a basis matching the result semantics for each step.
- When the operation result is a tax-inclusive amount (e.g., total = subtotal + tax), `tax_basis` should be `tax_inclusive`; tax-exclusive bases for summation should be `tax_exclusive`; the tax calculation itself may use `not_applicable`. When basis and result semantics mismatch, the report must flag and correct it.
- Amounts with different tax bases must not be directly added or compared; unify to a single basis before mixing.

### Raw Output Preservation

- Each calculation step saves: ① Input JSON (complete) ② Script stdout (complete raw output, no truncation or hand-written summaries) ③ stderr ④ Real exit code (capture the script's actual return value; never use `|| true` or similar to mask failures) ⑤ recalc.py file SHA-256.
- When a report references "complete output see xxx", that file must contain the script's full structured JSON output (including expression/result/rounding/warnings); input-only files do not qualify.
- All file SHA-256 hashes are listed in the audit report for post-hoc tool integrity verification.

### Rounding Declarations Must Match Inputs

- The rounding mode claimed in a report (e.g., ROUND_HALF_UP) must match the `rounding` parameter actually passed to the script.
- When no rounding parameter is passed, the script outputs `rounding: null`, `rounded: false`; the report must not claim rounding was applied.
- To verify rounding functionality, use an independent non-bid-data expression with an explicit `rounding` parameter, clearly distinguished from real bid price recalculation.

### Evidence Retention & Version Management

- Multiple review rounds for the same project each use their own directory; historical versions are never overwritten.
- Bilateral evidence in reports must include precise page/location references (e.g., B01-P1, I01, T01-P2 R05); vague references like "the bid document" are insufficient.
- Technical observations (image parameters, port counts, etc.) are explicitly distinguished from commercial conclusions: the price reviewer reports visual discrepancies and numerical mismatches; final technical determinations are made by the corresponding specialist.

## File Inventory

- `scripts/recalc.py` — recalculation script (standard library only; precise integer-coefficient arithmetic)
- `schemas/input.schema.json` — input Draft-07 Schema
- `schemas/output.schema.json` — output Draft-07 Schema
- `舍入与口径说明.md` — Basis registration table template (Chinese)
- `Basis-Reference.en.md` — Basis registration table template (English)
- `SKILL.zh-CN.md` — This document (Chinese version)
