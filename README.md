# Tender Price Review Agent

A specialist agent within the **Tender Review Team** (`tender-review-lead`)
that performs independent commercial bid price verification using auditable,
deterministic computation.

## Role in the Team

This agent accepts task assignments from the **Tender Review Lead**
(`tender-review-lead`) and delivers evidence-based commercial pricing reports.
It operates as a **member** of the team — it does not declare a bid compliant
or non-compliant; it provides data and candidate findings for the team lead to
summarize into a consolidated report. **Final procurement determinations are
made by a human reviewer.**

**What this agent does:**
- Independently recalculates bid amounts (line items, subtotals, tax, totals)
  using the `tender-price-recalc` skill with exact decimal arithmetic
- Records step-by-step evidence: input JSON, raw script stdout/stderr,
  real exit codes, and tool SHA-256 hashes
- Cross-checks tax rate consistency, unit consistency, and currency consistency
- Reports findings with bilateral evidence (tender requirement page ↔ bid
  response page ↔ calculation result)

**What this agent does NOT do:**
- Modify original bid documents or tender documents
- Declare a bid as "compliant" or "non-compliant" — the team lead summarizes
  combined findings, and a human reviewer makes final determinations
- Judge signature or seal authenticity
- Perform OCR on external documents (text/image processing uses the user's
  configured cloud model)
- Upload materials to external services beyond the configured model provider

## Capabilities

| Capability | Description |
|---|---|
| Price recalculation | Exact decimal arithmetic via `skills/tender-price-recalc/scripts/recalc.py` (Python stdlib only) |
| Tax verification | Validates tax amounts against declared rate and subtotal |
| Unit/currency check | Detects mismatches between stated units and numeric values |
| Evidence preservation | Saves input, output, exit codes, and SHA-256 for each step |
| Image observation | Reports visible parameters from technical images (transfers technical conclusions to the image review specialist) |

## Pre-use Checklist

Before running this agent, verify:

1. **Tender document (PDF)** is available in the project input directory; PDF
   text layer must be readable, or render mode must confirm page-level content.
2. **Bid document (PDF)** is available. If only DOCX is provided, it must be
   confirmed as fully parsed before treating it as equivalent to PDF; presence
   of a format mirror does not by itself confirm parse success.
3. **Technical image** (if referenced) is available for visual inspection by a
   model with vision capability.
4. **`skills/tender-price-recalc/scripts/recalc.py`** is present and its SHA
   matches the published hash.
5. **Python ≥ 3.8** is available on the system PATH.

## Input / Output

**Input:** JSON files following `skills/tender-price-recalc/schemas/input.schema.json` (Draft-07), with:
- `operation`: `sum` | `multiply` | `convert_unit` | `round`
- `currency`: ISO 4217 code (CNY, USD, EUR, JPY, GBP, HKD)
- `tax_basis`: `tax_inclusive` | `tax_exclusive` | `not_applicable`
- Operation-specific fields (operands, line_items, amount, etc.)

**Output:** JSON following `skills/tender-price-recalc/schemas/output.schema.json`:
- `status: "ok"` with expression, inputs echo, result, rounding, warnings
- `status: "rejected"` with errors array (never produces fake results)

## Error Handling

| Exit Code | Meaning | Output |
|---|---|---|
| 0 | Success — computation completed | Typically structured JSON to stdout; caller must verify before parsing |
| 2 | Input rejected — contract violation, unknown currency/tax basis, null value, non-finite number, parse failure, or value exceeds limits | Typically structured JSON (`status: "rejected"`) to stdout; caller must verify before parsing |
| 3 | Usage/IO error — input file unreadable, output path validation failed, or exclusive creation failed | Error message to **stderr only**; no output file written |

**Important for callers:**
- **Never infer JSON availability from the exit code alone.** Calculation
  or reportable input validation may produce JSON on stdout; however,
  argument parsing errors, output-size limit violations, file I/O failures,
  and refused output paths may produce stderr only. Empty or unparsable
  stdout is not a pass — callers must always check the actual exit code.
- Preserve raw stdout, stderr, and the real exit code for every step; parse
  stdout only when it contains valid JSON.
- With a valid `--output` target: input validation failure (exit code 2) may
  write rejected JSON to the output file; a refused output target (exit code 3)
  writes no file.
- Callers must preserve both stdout and stderr (not just one) for each step to
  maintain a complete audit trail.

## Scope & Limitations

- **Not a compliance tool**: This agent provides auxiliary review data, not
  legal or procurement compliance opinions.
- **No guarantee of winning**: Non-discovery of issues does not guarantee bid
  success.
- **Partial coverage acceptable**: When inputs are incomplete, the agent reports
  what was checked and what could not be checked — it never fills gaps with
  assumptions.
- **Observation ≠ determination**: Technical observations (IP rating from
  images, port counts, certificate dates) are reported as-is and transferred
  to the appropriate specialist. This agent does not make final technical
  determinations.
- **External dependencies**: Python and the configured LLM model are external
  to this agent and subject to their own licenses and availability.
- **Execution & privacy**: Script calculation and file extraction are performed
  within the connected DesireCore execution environment; the selected and
  authorized model channel processes any text or images sent to it — content
  does not necessarily remain on the user's local machine. Unauthorized OCR,
  email transmission, or requests to unfamiliar URLs are prohibited.

## Verification Status

The core skill (`tender-price-recalc`) has been verified using synthetic
samples and independent recalculation covering a limited set of arithmetic
and error-handling scenarios. This does not represent full-team coverage
or a general accuracy rate.

## Release Notes

- **Current version**: 0.1.0 (development/testing)
- Published version number and download URL: **not yet determined**

## License

MIT — see [LICENSE](./LICENSE).
