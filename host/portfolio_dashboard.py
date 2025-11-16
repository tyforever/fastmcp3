from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Tuple
import webbrowser

import pandas as pd


DATA_XLSX = Path("data/portfolio_positions.xlsx")
DATA_CSV = Path("data/portfolio_positions.csv")
DEFAULT_OUTPUT = Path("reports/portfolio_report.html")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {
        str(col): str(col).strip().lower()
        for col in df.columns
    }
    return df.rename(columns=renamed)


def load_positions_and_prices() -> Tuple[pd.DataFrame, pd.DataFrame]:
    if DATA_XLSX.exists():
        positions_df = _normalize_columns(pd.read_excel(DATA_XLSX, sheet_name="positions"))
        price_df = _normalize_columns(pd.read_excel(DATA_XLSX, sheet_name="price_map"))
    elif DATA_CSV.exists():
        positions_df = _normalize_columns(pd.read_csv(DATA_CSV))
        price_df = pd.DataFrame(columns=["symbol", "price"])
    else:
        raise FileNotFoundError("缺少 data/portfolio_positions.xlsx 或 data/portfolio_positions.csv")

    required_cols = {"symbol", "qty", "cost"}
    missing = required_cols - set(positions_df.columns)
    if missing:
        raise ValueError(f"positions 工作表缺少列: {', '.join(sorted(missing))}")

    if "price" not in price_df.columns:
        price_df = price_df.assign(price=pd.NA)

    positions_df["symbol"] = positions_df["symbol"].astype(str).str.upper()
    price_df["symbol"] = price_df["symbol"].astype(str).str.upper()

    merged = positions_df.merge(
        price_df[["symbol", "price"]],
        on="symbol",
        how="left",
        suffixes=("", "_from_price_map"),
    )
    if "price_from_price_map" in merged.columns:
        merged["price"] = merged["price"].fillna(merged["price_from_price_map"])
        merged = merged.drop(columns=["price_from_price_map"])

    if merged["price"].isna().any():
        missing = merged.loc[merged["price"].isna(), "symbol"].tolist()
        raise ValueError(f"缺少以下标的的价格: {', '.join(missing)}")

    merged["qty"] = merged["qty"].astype(float)
    merged["cost"] = merged["cost"].astype(float)
    merged["price"] = merged["price"].astype(float)

    return merged, price_df


def compute_metrics(portfolio_df: pd.DataFrame) -> dict:
    df = portfolio_df.copy()
    df["position_type"] = df["qty"].apply(lambda q: "多头" if q >= 0 else "空头")
    df["market_value"] = df["qty"] * df["price"]
    df["cost_value"] = df["qty"] * df["cost"]
    df["pnl"] = df["market_value"] - df["cost_value"]
    df["pnl_pct"] = df.apply(
        lambda row: (row["pnl"] / abs(row["cost_value"])) * 100 if row["cost_value"] else 0.0,
        axis=1,
    )

    totals = {
        "market_value": df["market_value"].sum(),
        "cost_value": df["cost_value"].sum(),
    }
    totals["pnl"] = totals["market_value"] - totals["cost_value"]
    totals["pnl_pct"] = (totals["pnl"] / abs(totals["cost_value"])) * 100 if totals["cost_value"] else 0.0

    long_df = df[df["position_type"] == "多头"]
    short_df = df[df["position_type"] == "空头"]

    def summarize(section: pd.DataFrame) -> dict:
        if section.empty:
            return {"market_value": 0.0, "cost_value": 0.0, "pnl": 0.0, "pnl_pct": 0.0}
        market_value = section["market_value"].sum()
        cost_value = section["cost_value"].sum()
        pnl = market_value - cost_value
        pnl_pct = (pnl / abs(cost_value)) * 100 if cost_value else 0.0
        return {
            "market_value": market_value,
            "cost_value": cost_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

    return {
        "portfolio": df,
        "totals": totals,
        "longs": summarize(long_df),
        "shorts": summarize(short_df),
    }


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def build_html(metrics: dict) -> str:
    totals = metrics["totals"]
    summary_cards = [
        ("总市值", format_currency(totals["market_value"])),
        ("总成本", format_currency(totals["cost_value"])),
        ("净盈亏", format_currency(totals["pnl"])),
        ("净盈亏%", format_pct(totals["pnl_pct"])),
    ]

    bucket_rows = [
        ("多头", metrics["longs"]),
        ("空头", metrics["shorts"]),
    ]
    df = metrics["portfolio"]
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def pnl_class(value: float) -> str:
        if value > 0:
            return "positive"
        if value < 0:
            return "negative"
        return ""

    detail_rows = []
    for _, row in df.iterrows():
        detail_rows.append(f"""
            <tr>
                <td>{row['symbol']}</td>
                <td>{row['position_type']}</td>
                <td>{row['qty']:.0f}</td>
                <td>{format_currency(row['cost'])}</td>
                <td>{format_currency(row['price'])}</td>
                <td>{format_currency(row['market_value'])}</td>
                <td>{format_currency(row['cost_value'])}</td>
                <td class="{pnl_class(row['pnl'])}">{format_currency(row['pnl'])}</td>
                <td class="{pnl_class(row['pnl'])}">{format_pct(row['pnl_pct'])}</td>
            </tr>
        """)

    bucket_table_rows = "".join(
        f"""
                    <tr>
                        <td style="text-align:center">{label}</td>
                        <td>{format_currency(bucket['market_value'])}</td>
                        <td>{format_currency(bucket['cost_value'])}</td>
                        <td class="{pnl_class(bucket['pnl'])}">{format_currency(bucket['pnl'])}</td>
                        <td class="{pnl_class(bucket['pnl'])}">{format_pct(bucket['pnl_pct'])}</td>
                    </tr>
        """
        for label, bucket in bucket_rows
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <title>组合盈亏看板</title>
    <style>
        body {{
            font-family: "Segoe UI", "PingFang SC", sans-serif;
            margin: 0;
            background: #f4f4f5;
            color: #111827;
        }}
        header {{
            background: #111827;
            color: white;
            padding: 20px 32px;
        }}
        main {{
            padding: 24px 32px 48px;
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin: 24px 0;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
        }}
        .card h3 {{
            font-size: 0.9rem;
            color: #6b7280;
            margin: 0 0 8px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }}
        .card p {{
            font-size: 1.4rem;
            margin: 0;
            font-weight: 600;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 16px;
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
        }}
        th, td {{
            padding: 12px 16px;
            text-align: right;
        }}
        th {{
            background: #1f2937;
            color: white;
            text-align: center;
        }}
        td:first-child, th:first-child {{
            text-align: left;
        }}
        td:nth-child(2), th:nth-child(2) {{
            text-align: center;
        }}
        tr:nth-child(even) td {{
            background: #f9fafb;
        }}
        .positive {{
            color: #15803d;
        }}
        .negative {{
            color: #b91c1c;
        }}
        .section-title {{
            margin-top: 40px;
            font-size: 1.2rem;
        }}
        .updated-at {{
            font-size: 0.9rem;
            color: #9ca3af;
        }}
    </style>
</head>
<body>
    <header>
        <h1>组合盈亏看板</h1>
        <p class="updated-at">最后更新：{updated_at}</p>
    </header>
    <main>
        <section class="cards">
            {''.join(f'<div class="card"><h3>{title}</h3><p>{value}</p></div>' for title, value in summary_cards)}
        </section>
        <section>
            <h2 class="section-title">多空持仓汇总</h2>
            <table>
                <thead>
                    <tr>
                        <th>方向</th>
                        <th>市值</th>
                        <th>成本</th>
                        <th>盈亏</th>
                        <th>盈亏%</th>
                    </tr>
                </thead>
                <tbody>
                    {bucket_table_rows}
                </tbody>
            </table>
        </section>
        <section>
            <h2 class="section-title">持仓明细</h2>
            <table>
                <thead>
                    <tr>
                        <th>标的</th>
                        <th>方向</th>
                        <th>数量</th>
                        <th>成本价</th>
                        <th>现价</th>
                        <th>市值</th>
                        <th>成本金额</th>
                        <th>盈亏</th>
                        <th>盈亏%</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(detail_rows)}
                </tbody>
            </table>
        </section>
    </main>
</body>
</html>
"""
    return html


def main():
    parser = argparse.ArgumentParser(description="生成组合盈亏的网页报告")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="HTML 报告输出路径")
    parser.add_argument("--open", action="store_true", help="生成后在默认浏览器中打开")
    args = parser.parse_args()

    portfolio_df, _ = load_positions_and_prices()
    metrics = compute_metrics(portfolio_df)

    html = build_html(metrics)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"报告已生成: {output_path.resolve()}")

    if args.open:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
