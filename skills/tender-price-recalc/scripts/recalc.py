#!/usr/bin/env python3
"""商务报价精确复算脚本（仅 Python 标准库）。

支持操作：
  - sum          金额加法汇总
  - multiply     数量×单价合计（多行汇总校验）
  - convert_unit 单位转换（万元 <-> 元）
  - round        按指定舍入规则舍入

算术模型（v2，修复精度静默丢值问题）：
  - 十进制字符串解析为精确整数三元组 (sign, coef, exp)，值 = sign*coef*10^exp；
    加法/乘法/除以 10000 全部在整数域精确完成，不使用全局 decimal context，
    不存在中间舍入、上溢、下溢或 normalize 丢值；
  - 8 种舍入模式用整数商与精确余数比较实现，取整不经过任何中间舍入；
  - 原始输入字符串原样保留在输出回显中，不做有损规范化；
  - 显式上限（见下方常量）：输入字符数、有效位数、指数、项数与输出长度，
    超界结构化拒绝；有限非零数绝不静默当零。

契约执行（v2）：
  - 按 schemas/input.schema.json 逐 operation 校验允许字段/必填/类型/数组与
    嵌套结构；不认识的键（如 sum 携带 unit、行内携带 tax_basis）明确拒绝，
    冲突口径要求 caller 先统一后重提；
  - 金额必须为字符串形式的十进制数；JSON 整数/浮点/布尔金额拒绝；
  - rounding 若出现必须是对象且同时含 mode 与 increment；rounding:null 拒绝。

安全与文件约束（v2）：
  - 只读输入文件，绝不修改输入；
  - 输出文件必须不存在：预校验输入与输出文件的身份与碰撞（规范路径 +
    同 inode/symlink/hardlink 检测，不只比较字符串），随后以排他模式
    (O_CREAT|O_EXCL) 打开写入，避免检查后再打开的竞态；
  - 覆盖策略：绝不覆盖任何已存在的普通文件、符号链接、目录，也不允许
    输出与输入为同一文件；需要重跑时请更换新的输出路径或先由调用方
    自行删除旧输出。校验失败不写出任何文件。
  - 严禁对输入执行 eval/exec/compile；
  - 拒绝：未知币种、未知含税口径、未知单位、空值（不当零）、非有限数
    （NaN/Infinity）、无法解析的输入、未知字段、超出数值上限的输入；
    拒绝时输出 status="rejected" 且退出码为 2。

用法：
  python3 recalc.py --input <输入.json> [--output <输出.json>]

退出码：
  0  成功
  2  输入被拒绝（契约校验失败、数值超限、口径未知、无法解析等）
  3  用法或 IO 错误（输入读取失败、输出路径安全校验失败、排他创建失败等；
     此时不写出任何输出文件）
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 常量：已知口径集合
# ---------------------------------------------------------------------------

KNOWN_CURRENCIES = frozenset({"CNY", "USD", "EUR", "JPY", "GBP", "HKD"})
KNOWN_TAX_BASIS = frozenset({"tax_inclusive", "tax_exclusive", "not_applicable"})
KNOWN_UNITS = frozenset({"yuan", "wan_yuan"})
OPERATIONS = frozenset({"sum", "multiply", "convert_unit", "round"})

ROUNDING_MODE_NAMES = frozenset({
    "ROUND_CEILING", "ROUND_DOWN", "ROUND_FLOOR", "ROUND_HALF_DOWN",
    "ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_UP", "ROUND_05UP",
})

UNIT_LABELS = {"yuan": "元", "wan_yuan": "万元"}

EXIT_OK = 0
EXIT_REJECTED = 2
EXIT_USAGE_IO = 3

# ---------------------------------------------------------------------------
# 显式上限（超界结构化拒绝；不追求任意巨大数字）
# ---------------------------------------------------------------------------

MAX_INPUT_CHARS = 128        # 单个数值字符串（去首尾空白后）最大长度
MAX_SIGNIFICANT_DIGITS = 64  # 单个数值最大有效位数
MAX_EXPONENT = 500           # 十进制指数绝对值上限（10^±500）
MAX_OPERANDS = 1000          # sum.operands 最大项数
MAX_LINE_ITEMS = 1000        # multiply.line_items 最大行数
MAX_OUTPUT_CHARS = 131072    # 输出 JSON 文本最大长度

# ---------------------------------------------------------------------------
# 契约：逐 operation 的允许字段集合（与 schemas/input.schema.json 一致，
# 全部 additionalProperties:false）
# ---------------------------------------------------------------------------

COMMON_FIELDS = ("operation", "currency", "tax_basis", "rounding")
ALLOWED_FIELDS = {
    "sum": frozenset(COMMON_FIELDS + ("operands",)),
    "multiply": frozenset(COMMON_FIELDS + ("line_items",)),
    "convert_unit": frozenset(COMMON_FIELDS + ("amount", "from_unit", "to_unit")),
    "round": frozenset(COMMON_FIELDS + ("amount",)),
}
ALLOWED_LINE_FIELDS = frozenset({"quantity", "unit_price"})
ALLOWED_ROUNDING_FIELDS = frozenset({"mode", "increment"})

# 十进制数字字面量（与 decimal.Decimal 接受的有限数语法一致，不含 NaN/Inf）
_NUMBER_RE = re.compile(
    r"^(?P<sign>[+-]?)"
    r"(?:(?P<int>\d+)(?:\.(?P<frac>\d*))?|\.(?P<frac2>\d+))"
    r"(?:[eE](?P<exp>[+-]?\d+))?$"
)


class RejectionError(Exception):
    """输入校验失败（契约违规、口径未知、空值、非有限数、超上限等）。"""


def reject(message):
    raise RejectionError(message)


# ---------------------------------------------------------------------------
# 精确十进制数：值 = sign * coef * 10^exp（coef 为非负整数，整数域精确）
# ---------------------------------------------------------------------------

class Dec(object):
    __slots__ = ("sign", "coef", "exp", "raw")

    def __init__(self, sign, coef, exp, raw):
        if coef == 0:
            sign = 1
        self.sign = sign
        self.coef = coef
        self.exp = exp
        self.raw = raw  # 原始输入字符串（原样保留，不做有损规范化）

    def is_zero(self):
        return self.coef == 0

    def is_negative(self):
        return self.sign < 0 and self.coef != 0


def parse_decimal(raw, context):
    """把字符串解析为精确 Dec。拒绝空值、非字符串、非有限数、无法解析与超上限输入。"""
    if raw is None:
        reject("空值不当零：%s 为空" % context)
    if isinstance(raw, bool):
        reject("%s 必须是数字字符串，收到布尔值" % context)
    if isinstance(raw, float):
        reject("%s 必须是字符串形式的数字（避免浮点失真），收到浮点数 %r" % (context, raw))
    if isinstance(raw, int):
        reject("%s 必须是字符串形式的数字（按已发布契约，金额不得为 JSON 整数/浮点），收到整数 %r"
               % (context, raw))
    if not isinstance(raw, str):
        reject("%s 必须是字符串形式的数字，收到 %s" % (context, type(raw).__name__))
    text = raw.strip()
    if text == "":
        reject("空值不当零：%s 为空字符串" % context)
    if len(text) > MAX_INPUT_CHARS:
        reject("%s 数值字符串长度 %d 超过上限 %d，拒绝（请核实原始数据后重提）"
               % (context, len(text), MAX_INPUT_CHARS))
    lowered = text.lower()
    if "nan" in lowered or "inf" in lowered:
        reject("非有限数被拒绝：%s = %r" % (context, raw))
    match = _NUMBER_RE.match(text)
    if match is None:
        reject("无法解析的数字：%s = %r" % (context, raw))
    digits = (match.group("int") or "") + (match.group("frac") or match.group("frac2") or "")
    if len(digits) > MAX_SIGNIFICANT_DIGITS:
        reject("%s 有效位数 %d 超过上限 %d，拒绝（本工具仅支持有限精度边界内的精确复算，"
               "超界请先与项目确认口径）" % (context, len(digits), MAX_SIGNIFICANT_DIGITS))
    frac_len = len(match.group("frac") or match.group("frac2") or "")
    exponent = -frac_len
    if match.group("exp") is not None:
        try:
            exponent += int(match.group("exp"))
        except ValueError:
            reject("无法解析的指数：%s = %r" % (context, raw))
    if abs(exponent) > MAX_EXPONENT:
        reject("%s 指数 %d 超出支持范围 ±%d，拒绝（有限非零数不会被静默当作 0）"
               % (context, exponent, MAX_EXPONENT))
    coef = int(digits) if digits else 0
    sign = -1 if match.group("sign") == "-" else 1
    return Dec(sign, coef, exponent, raw)


def _aligned_pair(a, b):
    """把两个 Dec 对齐到相同指数，返回 (sa, sb, exp)。整数域精确。"""
    if a.exp < b.exp:
        sa = a.sign * a.coef
        sb = b.sign * b.coef * (10 ** (b.exp - a.exp))
        return sa, sb, a.exp
    sa = a.sign * a.coef * (10 ** (a.exp - b.exp))
    sb = b.sign * b.coef
    return sa, sb, b.exp


def dec_add(a, b):
    sa, sb, exp = _aligned_pair(a, b)
    s = sa + sb
    sign = -1 if s < 0 else 1
    return Dec(sign, abs(s), exp, None)


def dec_mul(a, b):
    coef = a.coef * b.coef
    if coef == 0:
        return Dec(1, 0, a.exp + b.exp, None)
    return Dec(a.sign * b.sign, coef, a.exp + b.exp, None)


def dec_div_10000(a):
    """除以 10000：十进制下必然为有限小数，指数域精确完成，无舍入。"""
    return Dec(a.sign, a.coef, a.exp - 4, None)


def dec_mul_10000(a):
    return Dec(a.sign, a.coef, a.exp + 4, None)


def dec_to_str(a):
    """精确无损的十进制字符串（定点表示，不产生科学计数法，不丢有效数字；
    仅去除小数部分尾随零，不改变数值）。"""
    if a.coef == 0:
        return "0"
    digits = str(a.coef)
    prefix = "-" if a.sign < 0 else ""
    if a.exp >= 0:
        return prefix + digits + ("0" * a.exp)
    frac = -a.exp
    if len(digits) > frac:
        int_part, frac_part = digits[:-frac], digits[-frac:]
        frac_part = frac_part.rstrip("0")
        if frac_part:
            return prefix + int_part + "." + frac_part
        return prefix + int_part
    tail = (("0" * (frac - len(digits))) + digits).rstrip("0")
    return prefix + "0." + tail


def _check_result_size(value, context):
    text = dec_to_str(value)
    if len(text) > MAX_OUTPUT_CHARS:
        reject("%s 结果位数 %d 超过输出上限 %d，拒绝（避免不可复核的超长结果）"
               % (context, len(text), MAX_OUTPUT_CHARS))
    return text


# ---------------------------------------------------------------------------
# 按步长舍入：整数域精确实现，无中间舍入
# ---------------------------------------------------------------------------

def _divmod_by_dec(value, step):
    """整数域精确计算 |value| = q_true * step + r（q_true 非负整数，0 <= r < step）。

    返回 (q_true, r_dec)。构造：把两个数对齐到 rexp = min(指数) 后，
    分子 = coef_v * 10^(e_v - rexp)，分母 = coef_s * 10^(e_s - rexp)，
    于是 分子/分母 = |value|/step，q_true = 分子 // 分母，
    r = (分子 % 分母) * 10^rexp。全程整数，无舍入。
    """
    rexp = min(value.exp, step.exp)
    numerator = value.coef * (10 ** (value.exp - rexp))
    denominator = step.coef * (10 ** (step.exp - rexp))
    q, rem = divmod(numerator, denominator)
    return q, Dec(1, rem, rexp, None)


def _half_compare(remainder, step):
    """精确比较 |remainder| 与 step/2：返回 -1（小）、0（恰半）、1（大）。"""
    rexp = min(remainder.exp, step.exp)
    rem_scaled = remainder.coef * (10 ** (remainder.exp - rexp))
    step_scaled = step.coef * (10 ** (step.exp - rexp))
    left = 2 * rem_scaled
    return -1 if left < step_scaled else (1 if left > step_scaled else 0)


def _floor_to_step(value, step):
    """向零取整到步长：返回 (floor_dec, value_sign)。

    floor_dec 满足 |floor| <= |value|；单独回传原值符号，因为当 |floor|==0 时
    Dec 的符号被规范化为正，负数信息的保留必须由调用方持有。
    """
    q, _ = _divmod_by_dec(value, step)
    return Dec(value.sign, q * step.coef, step.exp, None), value.sign


def _step_multiple(floor_dec, step):
    """floor_dec 是 step 的多少倍（q_true；floor 结果必为步长的整数倍）。"""
    q, r = _divmod_by_dec(floor_dec, step)
    if not r.is_zero():
        raise AssertionError("internal: floor result must be a whole multiple of step")
    return q


def _step_away(original_sign, floor_dec, step):
    """在向下取整结果上向绝对值增大方向加一个步长；符号取原值符号。"""
    q = _step_multiple(floor_dec, step)
    return Dec(original_sign, (q + 1) * step.coef, step.exp, None)


def quantize_to_increment(value, mode_name, step):
    """按 8 种模式之一把 value 取整到 step 的整数倍。全程整数运算。"""
    if value.is_zero():
        return Dec(1, 0, step.exp, None)

    floor_dec, value_sign = _floor_to_step(value, step)
    # remainder = |value| - |floor_dec|，精确（与 floor 同一构造）
    _, rem_dec = _divmod_by_dec(value, step)

    if mode_name == "ROUND_DOWN":
        return floor_dec

    if mode_name == "ROUND_UP":
        if rem_dec.is_zero():
            return floor_dec
        return _step_away(value_sign, floor_dec, step)

    if mode_name == "ROUND_CEILING":
        if value.is_negative():
            return floor_dec
        if rem_dec.is_zero():
            return floor_dec
        return _step_away(value_sign, floor_dec, step)

    if mode_name == "ROUND_FLOOR":
        if not value.is_negative():
            return floor_dec
        if rem_dec.is_zero():
            return floor_dec
        return _step_away(value_sign, floor_dec, step)

    half = _half_compare(rem_dec, step)
    if mode_name == "ROUND_HALF_UP":
        return _step_away(value_sign, floor_dec, step) if half >= 0 else floor_dec
    if mode_name == "ROUND_HALF_DOWN":
        return _step_away(value_sign, floor_dec, step) if half > 0 else floor_dec
    if mode_name == "ROUND_HALF_EVEN":
        if half > 0:
            return _step_away(value_sign, floor_dec, step)
        if half < 0:
            return floor_dec
        # 恰半：取偶数倍
        q = _step_multiple(floor_dec, step)
        if q % 2 == 0:
            return floor_dec
        return _step_away(value_sign, floor_dec, step)

    if mode_name == "ROUND_05UP":
        # 与标准库 to_integral_value(ROUND_05UP) 一致：商为精确值（无截断）时
        # 不舍入；发生截断时，先向零取整，截断结果末位为 0 或 5 则向外（绝对值
        # 增大方向）再加一个步长，否则保持向零结果。
        if rem_dec.is_zero():
            return floor_dec
        q = _step_multiple(floor_dec, step)
        if q % 10 in (0, 5):
            return _step_away(value_sign, floor_dec, step)
        return floor_dec

    reject("未知舍入模式 %r" % mode_name)


# ---------------------------------------------------------------------------
# 契约校验工具（按已发布 input.schema.json）
# ---------------------------------------------------------------------------

def check_unknown_fields(data, allowed, context):
    unknown = sorted(set(data.keys()) - allowed)
    if unknown:
        reject("%s 包含契约之外的未知字段 %s；按已发布输入契约（additionalProperties: false）"
               "拒绝。请删除未知字段或先统一口径后重提，不猜测其语义"
               % (context, "、".join(unknown)))


def require_field(data, field, context):
    """取必填字段；缺失即拒绝。值为 null 由调用侧的类型检查拒绝（空值不当零）。"""
    if field not in data:
        reject("缺少必填字段 %s（%s）" % (field, context))
    return data[field]


def require_string(raw, field, context):
    if raw is None:
        reject("字段 %s 为空值；空值不当零，拒绝处理（%s）" % (field, context))
    if not isinstance(raw, str):
        reject("字段 %s 必须是字符串，收到 %s（%s）" % (field, type(raw).__name__, context))
    return raw


def validate_currency(raw, context):
    currency = require_string(raw, "currency", context)
    normalized = currency.strip().upper()
    if normalized not in KNOWN_CURRENCIES:
        reject("未知币种 %r（%s）；已知：%s。币种不明时暂停比较，不猜测"
               % (currency, context, "、".join(sorted(KNOWN_CURRENCIES))))
    return normalized


def validate_tax_basis(raw, context):
    basis = require_string(raw, "tax_basis", context).strip()
    if basis not in KNOWN_TAX_BASIS:
        reject("未知含税口径 %r（%s）；已知：%s。口径不明时暂停比较，不猜测"
               % (raw, context, "、".join(sorted(KNOWN_TAX_BASIS))))
    return basis


def validate_unit(raw, field, context):
    unit = require_string(raw, field, context)
    if unit not in KNOWN_UNITS:
        reject("未知单位 %r（%s）；已知：%s" % (unit, field, "、".join(sorted(KNOWN_UNITS))))
    return unit


def validate_rounding(spec, context):
    """返回 (mode_name, increment_dec)。字段值为 null 或非对象即拒绝（契约要求对象）。"""
    if spec is None:
        reject("字段 rounding 为 null；已发布契约要求其为对象（含 mode 与 increment）或整体省略，"
               "rounding:null 拒绝（%s）" % context)
    if not isinstance(spec, dict):
        reject("rounding 必须是对象（%s）；收到 %s，拒绝"
               % (context, type(spec).__name__))
    check_unknown_fields(spec, ALLOWED_ROUNDING_FIELDS, "rounding")
    if "mode" not in spec or spec["mode"] is None:
        reject("rounding.mode 缺失或为空（%s）；mode 与 increment 必须同时给出" % context)
    if "increment" not in spec or spec["increment"] is None:
        reject("rounding.increment 缺失或为空（%s）；mode 与 increment 必须同时给出" % context)
    mode_name = spec["mode"]
    if not isinstance(mode_name, str) or mode_name not in ROUNDING_MODE_NAMES:
        reject("未知舍入模式 %r（%s）；已知：%s"
               % (mode_name, context, "、".join(sorted(ROUNDING_MODE_NAMES))))
    increment = parse_decimal(spec["increment"], "%s 的 rounding.increment" % context)
    if increment.is_zero() or increment.is_negative():
        reject("rounding.increment 必须为正（%s）；零/负/非有限步长拒绝" % context)
    return (mode_name, increment)


# ---------------------------------------------------------------------------
# 操作实现（回显一律保留原始输入字符串）
# ---------------------------------------------------------------------------

def op_sum(payload, rounding_spec):
    operands_raw = require_field(payload, "operands", "sum")
    if not isinstance(operands_raw, list):
        reject("sum 的 operands 必须是数组，收到 %s" % type(operands_raw).__name__)
    if len(operands_raw) == 0:
        reject("sum 的 operands 不得为空数组（空值不当零）")
    if len(operands_raw) > MAX_OPERANDS:
        reject("sum 的 operands 项数 %d 超过上限 %d，拒绝" % (len(operands_raw), MAX_OPERANDS))
    values = []
    for index, item in enumerate(operands_raw):
        values.append(parse_decimal(item, "operands[%d]" % index))
    total = Dec(1, 0, 0, None)
    for value in values:
        total = dec_add(total, value)
    expression = " + ".join(dec_to_str(v) for v in values)
    result_value = total
    rounded = False
    if rounding_spec is not None:
        mode_name, increment = rounding_spec
        result_value = quantize_to_increment(total, mode_name, increment)
        rounded = True
    result_text = _check_result_size(result_value, "sum 结果")
    return {
        "expression": expression,
        "inputs": {"operands": [v.raw for v in values]},
        "result_value": result_text,
        "rounded": rounded,
        "warnings": [],
    }


def op_multiply(payload, rounding_spec):
    lines_raw = require_field(payload, "line_items", "multiply")
    if not isinstance(lines_raw, list):
        reject("multiply 的 line_items 必须是数组，收到 %s" % type(lines_raw).__name__)
    if len(lines_raw) == 0:
        reject("multiply 的 line_items 不得为空数组（空值不当零）")
    if len(lines_raw) > MAX_LINE_ITEMS:
        reject("multiply 的 line_items 行数 %d 超过上限 %d，拒绝"
               % (len(lines_raw), MAX_LINE_ITEMS))
    line_results = []
    expressions = []
    total = Dec(1, 0, 0, None)
    for index, line in enumerate(lines_raw):
        ctx = "line_items[%d]" % index
        if not isinstance(line, dict):
            reject("%s 必须是对象，收到 %s" % (ctx, type(line).__name__))
        check_unknown_fields(line, ALLOWED_LINE_FIELDS, ctx)
        quantity = parse_decimal(require_field(line, "quantity", ctx), "%s.quantity" % ctx)
        if quantity.is_zero() or quantity.is_negative():
            reject("%s.quantity 必须为正（零与负数拒绝）" % ctx)
        unit_price = parse_decimal(require_field(line, "unit_price", ctx),
                                   "%s.unit_price" % ctx)
        line_total = dec_mul(quantity, unit_price)
        total = dec_add(total, line_total)
        line_results.append({
            "quantity": quantity.raw,
            "unit_price": unit_price.raw,
            "line_total": dec_to_str(line_total),
        })
        expressions.append("%s × %s" % (dec_to_str(quantity), dec_to_str(unit_price)))
    expression = " + ".join(expressions) if len(expressions) > 1 else expressions[0]
    result_value = total
    rounded = False
    if rounding_spec is not None:
        mode_name, increment = rounding_spec
        result_value = quantize_to_increment(total, mode_name, increment)
        rounded = True
    result_text = _check_result_size(result_value, "multiply 结果")
    return {
        "expression": expression,
        "inputs": {"line_items": line_results},
        "result_value": result_text,
        "rounded": rounded,
        "warnings": [],
    }


def op_convert_unit(payload, rounding_spec):
    amount = parse_decimal(require_field(payload, "amount", "convert_unit"), "amount")
    from_unit = validate_unit(require_field(payload, "from_unit", "convert_unit"),
                              "from_unit", "convert_unit")
    to_unit = validate_unit(require_field(payload, "to_unit", "convert_unit"),
                            "to_unit", "convert_unit")
    if from_unit == to_unit:
        reject("from_unit 与 to_unit 相同（%s），单位转换无意义；请核对输入" % from_unit)

    warnings = []
    if from_unit == "wan_yuan" and to_unit == "yuan":
        converted = dec_mul_10000(amount)
        expression = "%s 万元 × 10000 = %s 元" % (dec_to_str(amount), dec_to_str(converted))
    else:  # yuan -> wan_yuan
        converted = dec_div_10000(amount)
        expression = "%s 元 ÷ 10000 = %s 万元" % (dec_to_str(amount), dec_to_str(converted))
        # 十进制金额除以 10000 恒为有限小数（仅移动小数点），转换无损、无"除不尽"，
        # 故不在此发出算术警告；万元保留位数属项目口径，应在登记表另行约定。

    result_value = converted
    rounded = False
    if rounding_spec is not None:
        mode_name, increment = rounding_spec
        result_value = quantize_to_increment(converted, mode_name, increment)
        rounded = True
    result_text = _check_result_size(result_value, "convert_unit 结果")
    return {
        "expression": expression,
        "inputs": {"amount": amount.raw, "from_unit": from_unit, "to_unit": to_unit},
        "result_value": result_text,
        "rounded": rounded,
        "warnings": warnings,
        "result_unit": to_unit,
    }


def op_round(payload, rounding_spec):
    amount = parse_decimal(require_field(payload, "amount", "round"), "amount")
    if rounding_spec is None:
        reject("round 操作必须提供 rounding（mode 与 increment）；舍入规则不明不猜测")
    mode_name, increment = rounding_spec
    result_value = quantize_to_increment(amount, mode_name, increment)
    result_text = _check_result_size(result_value, "round 结果")
    return {
        "expression": "round(%s, mode=%s, increment=%s) = %s" % (
            dec_to_str(amount), mode_name, dec_to_str(increment), result_text),
        "inputs": {"amount": amount.raw},
        "result_value": result_text,
        "rounded": True,
        "warnings": [],
    }


OPERATION_FUNCS = {
    "sum": op_sum,
    "multiply": op_multiply,
    "convert_unit": op_convert_unit,
    "round": op_round,
}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def process(request):
    """返回 (输出 dict, 退出码)。拒绝时输出 status='rejected'。"""
    try:
        if not isinstance(request, dict):
            reject("输入顶层必须是 JSON 对象")

        operation = require_field(request, "operation", "顶层")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            reject("未知操作 %r；已知：%s" % (operation, "、".join(sorted(OPERATIONS))))

        # 顶层契约：未知字段拒绝（含任何与口径冲突的附加字段）
        check_unknown_fields(request, ALLOWED_FIELDS[operation], "顶层")

        currency = validate_currency(require_field(request, "currency", "顶层"), "顶层")
        tax_basis = validate_tax_basis(require_field(request, "tax_basis", "顶层"), "顶层")
        if "rounding" in request:
            rounding = validate_rounding(request["rounding"], "顶层")
        elif operation == "round":
            reject("缺少必填字段 rounding（顶层）；round 操作必须提供 rounding")
        else:
            rounding = None

        computed = OPERATION_FUNCS[operation](request, rounding)

        result_unit = computed.get("result_unit", "yuan")
        if operation in ("sum", "multiply", "round"):
            result_unit = "yuan"  # 默认元；项目以万元计价的请先用 convert_unit 统一口径

        output = {
            "status": "ok",
            "operation": operation,
            "expression": computed["expression"],
            "inputs": {
                "currency": currency,
                "tax_basis": tax_basis,
                "operation_payload": computed["inputs"],
            },
            "result": {
                "value": computed["result_value"],
                "unit": result_unit,
                "currency": currency,
                "tax_basis": tax_basis,
                "rounded": computed["rounded"],
            },
            "rounding": (
                {"mode": rounding[0], "increment": dec_to_str(rounding[1])}
                if rounding is not None else None
            ),
            "warnings": computed["warnings"],
        }
        return output, EXIT_OK

    except RejectionError as exc:
        output = {
            "status": "rejected",
            "errors": [str(exc)],
            "warnings": [],
        }
        return output, EXIT_REJECTED


# ---------------------------------------------------------------------------
# 文件安全：输入/输出身份与碰撞预校验 + 排他创建写入
# ---------------------------------------------------------------------------

def _describe_path(path):
    """返回 (规范路径, 是否为符号链接)。符号链接以 lstat 判定，不跟随。"""
    is_link = os.path.islink(path)
    return os.path.realpath(path), is_link


def _same_file_identity(path_a, path_b):
    """同文件身份判定：规范路径相同，或 (设备, inode) 相同（覆盖 hardlink）。"""
    if os.path.realpath(path_a) == os.path.realpath(path_b):
        return True
    try:
        stat_a = os.stat(path_a)
        stat_b = os.stat(path_b)
    except OSError:
        return False
    return (stat_a.st_dev, stat_a.st_ino) == (stat_b.st_dev, stat_b.st_ino)


def validate_output_path(input_path, output_path):
    """预校验输出路径：失败即拒绝（不写任何文件）。

    规则：
      1. 输出路径不得是已存在的普通文件、符号链接、目录或其他对象；
      2. 输出与输入不得为同一文件（规范路径相同、同 inode、符号链接指向输入均拒绝）；
      3. 拒绝经符号链接逃逸出所选输出父目录的碰撞目标由 1、2 覆盖。
    """
    out_real, out_is_link = _describe_path(output_path)
    if out_is_link:
        reject("输出路径是符号链接，拒绝（不得通过已有链接写出或覆盖目标）：%s" % output_path)
    if os.path.lexists(output_path):
        reject("输出路径已存在，拒绝覆盖（本工具绝不覆盖已有文件；"
               "请更换新输出路径或由调用方先删除旧输出后重跑）：%s" % output_path)
    if os.path.isdir(out_real) or os.path.lexists(out_real):
        reject("输出目标已存在（含经父目录符号链接解析后的目标），拒绝：%s" % output_path)
    if _same_file_identity(input_path, output_path):
        reject("输出路径与输入文件为同一文件（规范路径或设备/索引节点相同），"
               "拒绝写出以免截断输入原件：%s" % output_path)


def read_input(input_path):
    try:
        with open(input_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        sys.stderr.write("无法读取输入文件：%s\n" % exc)
        raise SystemExit(EXIT_USAGE_IO)


def emit_output(output, output_path):
    """写出结果。指定 --output 时：校验失败/排他创建失败一律不写文件、退出码 3。"""
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if len(text) > MAX_OUTPUT_CHARS:
        sys.stderr.write("输出文本长度 %d 超过上限 %d，拒绝写出；请拆分计算后重提\n"
                         % (len(text), MAX_OUTPUT_CHARS))
        raise SystemExit(EXIT_REJECTED)
    if output_path is None:
        sys.stdout.write(text + "\n")
        return
    try:
        # 排他创建（O_CREAT|O_EXCL）：目标已存在（普通文件/符号链接/目录）时
        # 内核级拒绝，不存在"检查后再打开"的窗口。
        fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        sys.stderr.write("输出路径已存在，拒绝覆盖：%s（请更换新路径后重跑）\n" % output_path)
        raise SystemExit(EXIT_USAGE_IO)
    except OSError as exc:
        sys.stderr.write("无法创建输出文件：%s\n" % exc)
        raise SystemExit(EXIT_USAGE_IO)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError as exc:
        sys.stderr.write("无法写出输出文件：%s（已移除半成品）\n" % exc)
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise SystemExit(EXIT_USAGE_IO)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="商务报价精确复算（十进制精确整数运算、可复算、拒绝不明口径与未知字段）")
    parser.add_argument("--input", required=True, help="输入 JSON 文件路径（只读）")
    parser.add_argument("--output", default=None,
                        help="输出 JSON 文件路径（必须不存在；省略则打印到 stdout）")
    args = parser.parse_args(argv)

    if args.output is not None:
        try:
            validate_output_path(args.input, args.output)
        except RejectionError as exc:
            sys.stderr.write("输出路径校验失败：%s\n" % exc)
            return EXIT_USAGE_IO

    raw_text = read_input(args.input)

    try:
        request = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        output = {"status": "rejected",
                  "errors": ["输入不是合法 JSON：%s" % exc],
                  "warnings": []}
        emit_output(output, args.output)
        return EXIT_REJECTED

    try:
        output, exit_code = process(request)
    except Exception as exc:  # 兜底：任何意外数值/运行时异常都转为结构化拒绝
        output = {"status": "rejected",
                  "errors": ["计算过程出现未预期异常，拒绝输出伪精确结果：%s: %s"
                             % (type(exc).__name__, exc)],
                  "warnings": []}
        exit_code = EXIT_REJECTED
    emit_output(output, args.output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
