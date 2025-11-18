from __future__ import annotations

from typing import Dict, List, Optional


def register_invest_tools() -> Dict[str, dict]:
    return {
        "calc_position_pnl": {
            "description": "计算单个持仓盈亏，支持多空方向与手续费",
            "parameters": {
                "symbol": {"type": "string", "description": "标的代码，可选"},
                "cost": {"type": "number", "description": "建仓价格（正数）"},
                "qty": {"type": "number", "description": "持仓数量，负数表示空头"},
                "price": {"type": "number", "description": "当前价格"},
                "fee_rate": {
                    "type": "number",
                    "description": "可选：双边手续费率，默认 0",
                },
            },
            "required": ["cost", "qty", "price"],
            "callable": calc_position_pnl,
        },
        "calc_portfolio_pnl": {
            "description": "计算组合盈亏，输入多仓位行及实时价格映射",
            "parameters": {
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "每行至少包含 symbol/cost/qty，可附带 price",
                },
                "price_map": {
                    "type": "object",
                    "description": "可选：symbol -> 最新价的映射，覆盖行内 price",
                },
                "fee_rate": {
                    "type": "number",
                    "description": "可选：双边手续费率，默认 0",
                },
            },
            "required": ["rows"],
            "callable": calc_portfolio_pnl,
        },
        "analyze_portfolio_quality": {
            "description": "基于组合明细检查缺失价格和异常数量，并返回文字提示",
            "parameters": {
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "同 calc_portfolio_pnl，至少包含 symbol/qty/cost",
                },
                "price_map": {
                    "type": "object",
                    "description": "可选价格映射，覆盖行内 price",
                },
                "max_abs_qty": {
                    "type": "number",
                    "description": "数量绝对值判定异常的阈值，默认 1000000",
                },
            },
            "required": ["rows"],
            "callable": analyze_portfolio_quality,
        },
        "simulate_scenarios": {
            "description": "基于调整参数多次调用 calc_portfolio_pnl，输出情景对比",
            "parameters": {
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "基础持仓数据，至少包含 symbol/qty/cost/price",
                },
                "price_map": {
                    "type": "object",
                    "description": "可选：覆盖行内价格的映射",
                },
                "adjustments": {
                    "type": "array",
                    "description": "每个元素包含 label/pct/delta，用于指定涨跌百分比或绝对价调整",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "pct": {"type": "number"},
                            "delta": {"type": "number"},
                        },
                    },
                },
                "fee_rate": {
                    "type": "number",
                    "description": "可选：双边手续费率，默认 0",
                },
            },
            "required": ["rows"],
            "callable": simulate_scenarios,
        },
    }


def calc_position_pnl(cost: float, qty: float, price: float, symbol: Optional[str] = None,
                      fee_rate: float = 0.0) -> dict:
    qty = float(qty)
    cost = float(cost)
    price = float(price)
    side = "long" if qty >= 0 else "short"
    abs_qty = abs(qty)

    gross_cost = cost * abs_qty
    market_value = price * abs_qty
    pnl = (price - cost) * qty
    notional = cost * abs_qty if cost else 0
    pnl_pct = (pnl / notional) if notional else 0

    total_fee = fee_rate * (gross_cost + market_value) if fee_rate else 0
    net_pnl = pnl - total_fee
    net_pnl_pct = (net_pnl / notional) if notional else 0

    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "cost_price": cost,
        "market_price": price,
        "gross_cost_value": gross_cost,
        "market_value": market_value,
        "gross_pnl": pnl,
        "gross_pnl_pct": pnl_pct,
        "fees": total_fee,
        "net_pnl": net_pnl,
        "net_pnl_pct": net_pnl_pct,
        "breakeven_price": cost,
    }


def calc_portfolio_pnl(rows: List[dict], price_map: Optional[Dict[str, float]] = None,
                       fee_rate: float = 0.0) -> dict:
    if not rows:
        return {"error": "rows 不能为空"}

    price_map = price_map or {}

    totals = {
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "gross_cost_value": 0.0,
        "market_value": 0.0,
        "fees": 0.0,
    }
    long_totals = {
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "gross_cost_value": 0.0,
        "market_value": 0.0,
        "fees": 0.0,
    }
    short_totals = {
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "gross_cost_value": 0.0,
        "market_value": 0.0,
        "fees": 0.0,
    }

    details = []
    for row in rows:
        symbol = row.get("symbol")
        qty = row.get("qty")
        cost = row.get("cost")
        if qty is None or cost is None:
            details.append({
                "symbol": symbol,
                "error": "缺少 qty 或 cost",
            })
            continue

        qty = float(qty)
        cost = float(cost)
        price = row.get("price")
        if symbol and symbol in price_map:
            price = price_map[symbol]
        if price is None:
            details.append({
                "symbol": symbol,
                "error": "缺少 price，且 price_map 未提供",
            })
            continue

        position = calc_position_pnl(cost=cost, qty=qty, price=float(price),
                                     symbol=symbol, fee_rate=fee_rate)
        details.append(position)

        for key in ["gross_pnl", "net_pnl", "gross_cost_value", "market_value", "fees"]:
            totals[key] += position[key]

        bucket = long_totals if position["side"] == "long" else short_totals
        for key in ["gross_pnl", "net_pnl", "gross_cost_value", "market_value", "fees"]:
            bucket[key] += position[key]

    invested = totals["gross_cost_value"]
    totals["gross_pnl_pct"] = (totals["gross_pnl"] / invested) if invested else 0
    totals["net_pnl_pct"] = (totals["net_pnl"] / invested) if invested else 0

    for bucket in (long_totals, short_totals):
        invested_bucket = bucket["gross_cost_value"]
        bucket["gross_pnl_pct"] = (bucket["gross_pnl"] / invested_bucket) if invested_bucket else 0
        bucket["net_pnl_pct"] = (bucket["net_pnl"] / invested_bucket) if invested_bucket else 0

    return {
        "totals": totals,
        "longs": long_totals,
        "shorts": short_totals,
        "positions": details,
        "position_count": len(details),
    }


def analyze_portfolio_quality(rows: List[dict], price_map: Optional[Dict[str, float]] = None,
                              max_abs_qty: float = 1_000_000) -> dict:
    """Check calc_portfolio_pnl output and summarize potential data issues."""
    pnl_result = calc_portfolio_pnl(rows=rows, price_map=price_map)
    details = pnl_result.get("positions", [])

    warnings: List[str] = []
    missing_price_symbols: List[str] = []
    zero_qty_symbols: List[str] = []
    oversized_qty_symbols: List[str] = []
    zero_cost_symbols: List[str] = []

    for item in details:
        symbol = item.get("symbol") or "未命名标的"
        if "error" in item:
            if "price" in item["error"]:
                missing_price_symbols.append(symbol)
            warnings.append(f"{symbol}: {item['error']}")
            continue

        qty = item.get("qty")
        cost_price = item.get("cost_price")
        if qty == 0:
            zero_qty_symbols.append(symbol)
        elif qty is not None and abs(qty) > max_abs_qty:
            oversized_qty_symbols.append(symbol)

        if cost_price in (None, 0):
            zero_cost_symbols.append(symbol)

    if missing_price_symbols:
        warnings.append(f"缺少价格: {', '.join(sorted(set(missing_price_symbols)))}")
    if zero_qty_symbols:
        warnings.append(f"数量为 0: {', '.join(sorted(set(zero_qty_symbols)))}")
    if oversized_qty_symbols:
        warnings.append(
            f"数量绝对值超过阈值 {max_abs_qty}: {', '.join(sorted(set(oversized_qty_symbols)))}"
        )
    if zero_cost_symbols:
        warnings.append(f"成本价为 0: {', '.join(sorted(set(zero_cost_symbols)))}")

    status = "ok" if not warnings else "warning"
    if warnings:
        summary = "数据存在异常，请优先处理以下问题：\n- " + "\n- ".join(warnings)
    else:
        summary = "未发现明显的数据质量或数量异常，当前组合数据可用于进一步分析。"

    return {
        "status": status,
        "warnings": warnings,
        "summary": summary,
        "position_count": len(details),
        "pnl_snapshot": pnl_result.get("totals"),
    }


def _summarize_totals(totals: Optional[dict]) -> dict:
    if not totals:
        return {}
    return {
        "market_value": totals.get("market_value", 0.0),
        "cost_value": totals.get("gross_cost_value", 0.0),
        "pnl": totals.get("net_pnl", totals.get("gross_pnl", 0.0)),
        "pnl_pct": totals.get("net_pnl_pct", totals.get("gross_pnl_pct", 0.0)),
    }


def simulate_scenarios(rows: List[dict], price_map: Optional[Dict[str, float]] = None,
                       adjustments: Optional[List[dict]] = None, fee_rate: float = 0.0) -> dict:
    """Run calc_portfolio_pnl under different pct/price adjustments."""
    base_result = calc_portfolio_pnl(rows=rows, price_map=price_map, fee_rate=fee_rate)
    details = base_result.get("positions", [])
    valid_positions = [item for item in details if "error" not in item]
    invalid_positions = [item for item in details if "error" in item]

    specs = adjustments or [{"label": "当前价格", "pct": 0.0, "delta": 0.0}]
    normalized_specs = []
    for idx, spec in enumerate(specs):
        pct = float(spec.get("pct", 0.0))
        delta = float(spec.get("delta", 0.0))
        label = spec.get("label") or f"情景 {idx + 1}"
        normalized_specs.append({
            "label": label,
            "pct": pct,
            "delta": delta,
        })

    scenarios = []
    if valid_positions:
        for spec in normalized_specs:
            adjusted_rows = []
            for pos in valid_positions:
                base_price = pos.get("market_price")
                if base_price is None:
                    continue
                new_price = base_price * (1 + spec["pct"]) + spec["delta"]
                new_price = max(new_price, 0.0)
                adjusted_rows.append({
                    "symbol": pos.get("symbol"),
                    "qty": pos.get("qty"),
                    "cost": pos.get("cost_price"),
                    "price": new_price,
                })

            if not adjusted_rows:
                snapshot = {}
            else:
                snapshot = _summarize_totals(
                    calc_portfolio_pnl(rows=adjusted_rows, fee_rate=fee_rate).get("totals")
                )

            scenarios.append({
                "label": spec["label"],
                "pct": spec["pct"],
                "delta": spec["delta"],
                "totals": snapshot,
            })
    else:
        scenarios.append({
            "label": normalized_specs[0]["label"],
            "pct": normalized_specs[0]["pct"],
            "delta": normalized_specs[0]["delta"],
            "totals": {},
        })

    return {
        "base_totals": _summarize_totals(base_result.get("totals")),
        "scenarios": scenarios,
        "invalid_positions": invalid_positions,
        "position_count": len(details),
    }
