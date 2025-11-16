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
