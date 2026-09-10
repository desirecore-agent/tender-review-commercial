# Rounding & Basis Reference (English)

Before recalculating any amounts, the basis must be fixed. **If any field is empty or contradictory, pause any comparison or summation involving that amount and report the uncertainty — never guess or assume.**

## 1. Currency

Known currency codes (ISO 4217): `CNY`, `USD`, `EUR`, `JPY`, `GBP`, `HKD`.
Other currencies → rejection (unknown currency). No automatic conversion or comparison across different currencies.

## 2. Unit

| Code | Meaning | Conversion |
|---|---|---|
| `yuan` | Yuan (元) | 1 yuan |
| `wan_yuan` | Wan Yuan (万元) | 1 wan_yuan = 10000 yuan |

- Summation (`sum`/`multiply`) and rounding (`round`) only support **yuan** as the calculation unit; the result unit is always `yuan`. If the project prices in wan_yuan, use `convert_unit` to unify to yuan first, then resubmit.
- **Unit conflicts are never silently downgraded**: Any `unit` key outside the contract (e.g., adding `unit: "wan_yuan"` to a `sum` request) is rejected — the caller must unify the basis first; the script never guesses the semantics of unknown fields, preventing wan_yuan values from being used as yuan.
- When a document says "wan_yuan" but the table values appear to be in yuan (or vice versa): register the discrepancy, pause comparison, and wait for project clarification.

## 3. Tax Basis

| Code | Meaning |
|---|---|
| `tax_inclusive` | Tax-inclusive price |
| `tax_exclusive` | Tax-exclusive price |
| `not_applicable` | Not applicable (e.g., non-tax amounts, quantities) |

Tax-inclusive and tax-exclusive amounts must not be directly added or compared; conversion requires a known tax rate, which must be recorded separately as an explicit input — the script does not assume any default rate.

**Line-level basis conflicts are rejected**: Line items (`line_items` objects) only allow `quantity` and `unit_price` keys; if `tax_basis` or other basis fields appear at line level and conflict with the top-level basis, the entire request is rejected and the caller must unify the basis and resubmit.

## 4. Rounding Conventions

- 8 rounding mode names: `ROUND_HALF_UP` (standard rounding), `ROUND_HALF_EVEN` (banker's rounding), `ROUND_DOWN`, `ROUND_UP`, `ROUND_CEILING`, `ROUND_FLOOR`, `ROUND_HALF_DOWN`, `ROUND_05UP` (round toward zero to increment; if truncated result ends in 0 or 5, add one increment away from zero).
- Common `increment` values: `"0.01"` (to fen), `"1"` (to yuan), `"0.05"` (to 5 fen); increment must be positive; zero/negative is rejected.
- The `rounding` field: omission means no rounding (exact decimal result is preserved, `rounded: false`); value of `null` or non-object is rejected (contract requires object or omission). The `round` operation always requires `rounding`.
- Rounding is completed entirely in the integer domain (exact quotient and remainder comparison); there is no intermediate rounding that could cross a final rounding boundary.
- When a project has additional rules (e.g., "unit prices to two decimals, totals not separately rounded"), follow the project's rules and record them in the basis registration table's "project-specific conventions" column.

## 5. Numeric Limits (exceeding = structured rejection)

| Limit | Upper Bound |
|---|---|
| Single numeric string length | 128 characters |
| Single numeric significant digits | 64 digits |
| Decimal exponent absolute value | 500 |
| `sum.operands` item count / `multiply.line_items` line count | 1000 |
| Output JSON text length | 128 KiB |

All exceedances return `status: "rejected"` (exit code 2); finite non-zero numbers are never silently treated as zero.

## 6. File & Overwrite Policy

- Input files are read-only; output is only written to **non-existent** paths (exclusive creation).
- Output and input on the same path, mutually symlinked/hardlinked, or output pointing to an existing regular file/symlink/directory → rejection (exit code 3); no files are written.
- Re-run the same calculation: use a new output path, or have the caller delete the old output first; the script does not overwrite on its own.

## 7. Basis Registration Table Template (one per project)

| Amount Item | Source Location | Currency | Unit | Tax Basis | Rounding Rule | Notes |
|---|---|---|---|---|---|---|
| Opening summary total |  |  |  |  |  |  |
| Line-item summary total |  |  |  |  |  |  |
| Amount in words |  |  |  |  | N/A | Figure/word comparison recorded separately |

## 8. Null & Exception Handling

- Amount not found → record "not found"; **do not** treat as 0 in summations.
- NaN / Infinity / unparseable number / value exceeds limits → rejection.
- Unit price, quantity, and subtotal inconsistency → provide a candidate correction, noting that correction is subject to the tender document's rules; do not automatically declare invalidity.
