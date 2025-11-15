def calc_pnl(cost: float, price: float, qty: float):
    return (price - cost) * qty


def register_invest_tools():
    return {
        "calc_pnl": {
            "description": "计算盈亏",
            "parameters": {
                "cost": {"type": "number"},
                "price": {"type": "number"},
                "qty": {"type": "number"},
            },
            "callable": calc_pnl,
        }
    }
