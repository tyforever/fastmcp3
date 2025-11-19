from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
        suffixes=("", "_map"),
    )
    if "price_map" in merged.columns:
        merged["price"] = merged["price"].fillna(merged["price_map"])
        merged = merged.drop(columns=["price_map"])

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
        "longs": summarize(df[df["position_type"] == "多头"]),
        "shorts": summarize(df[df["position_type"] == "空头"]),
    }


def _describe_top_positions(df: pd.DataFrame, n: int = 2) -> str:
    if df.empty:
        return "暂无持仓"

    winners = df.nlargest(n, "pnl")
    losers = df.nsmallest(n, "pnl")

    parts = []
    if not winners.empty:
        win_desc = "；".join(
            f"{row['symbol']} 盈亏 {row['pnl']:.2f}({row['pnl_pct']:+.2f}%)"
            for _, row in winners.iterrows()
        )
        parts.append(f"领先标的：{win_desc}")

    if not losers.empty:
        lose_desc = "；".join(
            f"{row['symbol']} 盈亏 {row['pnl']:.2f}({row['pnl_pct']:+.2f}%)"
            for _, row in losers.iterrows()
        )
        parts.append(f"拖累标的：{lose_desc}")

    return "；".join(parts)


def build_fallback_analysis(metrics: dict, scenario_data: Optional[dict]) -> str:
    df: pd.DataFrame = metrics["portfolio"]
    totals = metrics["totals"]
    longs = metrics["longs"]
    shorts = metrics["shorts"]

    total_market = totals.get("market_value", 0.0)
    long_mv = longs.get("market_value", 0.0)
    short_mv = shorts.get("market_value", 0.0)
    long_share = f"{long_mv / total_market:.1%}" if total_market else "0%"
    short_share = f"{short_mv / total_market:.1%}" if total_market else "0%"

    lines = [
        f"组合市值 {totals.get('market_value', 0.0):,.2f}，净盈亏 {totals.get('pnl', 0.0):,.2f} ({totals.get('pnl_pct', 0.0):+.2f}%)。",
        f"多头市值占比 {long_share}，空头市值占比 {short_share}。",
        _describe_top_positions(df),
    ]

    scenarios = (scenario_data or {}).get("scenarios") or []
    if scenarios:
        ranked = sorted(
            scenarios,
            key=lambda item: (item.get("totals") or {}).get("pnl", float("-inf")),
            reverse=True,
        )
        best = ranked[0]
        worst = ranked[-1]
        base_totals = (scenario_data or {}).get("base") or {}
        base_pnl = base_totals.get("pnl")

        def _fmt(item: dict) -> str:
            totals = item.get("totals") or {}
            return f"{item.get('label')}: 净盈亏 {totals.get('pnl', 0.0):,.2f} ({totals.get('pnl_pct', 0.0):+.2f}%)"

        scenario_lines = ["情景模拟摘要：", _fmt(best)]
        if best is not worst:
            scenario_lines.append(_fmt(worst))
        if base_pnl is not None:
            scenario_lines.append(f"当前价格基准盈亏 {base_pnl:,.2f}。")
        lines.append(" ".join(scenario_lines))

    return "\n".join(line for line in lines if line)


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def format_shift(pct: float, delta: float) -> str:
    pct_part = f"{pct * 100:+.1f}%" if pct else ""
    delta_part = f"{delta:+.2f}" if delta else ""
    if pct_part and delta_part:
        return f"{pct_part} / {delta_part}"
    return pct_part or delta_part or "0%"


def build_scenario_rows(scenario_data: Optional[dict]) -> str:
    if not scenario_data:
        return "<p>暂无情景结果，可通过 CLI 指定 --scenario 后由模型更新。</p>"

    scenarios = scenario_data.get("scenarios") or []
    if not scenarios:
        return "<p>暂无情景结果，可通过 CLI 指定 --scenario 后由模型更新。</p>"

    rows = []
    base_totals = scenario_data.get("base_totals") or {}
    for item in scenarios:
        totals = item.get("totals") or {}
        pnl = totals.get("pnl")
        pnl_pct = totals.get("pnl_pct")
        rows.append(f"""
            <tr>
                <td>{item.get('label')}</td>
                <td>{format_shift(item.get('pct', 0.0), item.get('delta', 0.0))}</td>
                <td>{format_currency(totals.get('market_value', 0.0)) if totals else '-'}</td>
                <td>{format_currency(totals.get('cost_value', 0.0)) if totals else '-'}</td>
                <td class="{ 'positive' if (pnl or 0) > 0 else 'negative' if (pnl or 0) < 0 else '' }">
                    {format_currency(pnl) if pnl is not None else '-'}
                </td>
                <td class="{ 'positive' if (pnl or 0) > 0 else 'negative' if (pnl or 0) < 0 else '' }">
                    {format_pct(pnl_pct) if pnl_pct is not None else '-'}
                </td>
            </tr>
        """)

    base_row = ""
    if base_totals:
        base_row = f"""
            <tr class="scenario-base">
                <td>当前价格</td>
                <td>基准</td>
                <td>{format_currency(base_totals.get('market_value', 0.0))}</td>
                <td>{format_currency(base_totals.get('cost_value', 0.0))}</td>
                <td class="{ 'positive' if base_totals.get('pnl', 0.0) > 0 else 'negative' if base_totals.get('pnl', 0.0) < 0 else '' }">
                    {format_currency(base_totals.get('pnl', 0.0))}
                </td>
                <td class="{ 'positive' if base_totals.get('pnl', 0.0) > 0 else 'negative' if base_totals.get('pnl', 0.0) < 0 else '' }">
                    {format_pct(base_totals.get('pnl_pct', 0.0))}
                </td>
            </tr>
        """

    return f"""
        <table class="scenario-table">
            <thead>
                <tr>
                    <th>情景</th>
                    <th>调整幅度</th>
                    <th>市值</th>
                    <th>成本</th>
                    <th>净盈亏</th>
                    <th>净盈亏%</th>
                </tr>
            </thead>
            <tbody>
                {base_row}
                {''.join(rows)}
            </tbody>
        </table>
    """


def build_html(
    metrics: dict,
    quality_text: Optional[str] = None,
    scenario_data: Optional[dict] = None,
    analysis_text: Optional[str] = None,
) -> str:
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
    quality_notes = (quality_text or "暂无模型提示。").strip()
    analysis_notes = (analysis_text or "暂无模型分析，请在 host_app 中触发模型调用。").strip()
    quality_html = "<br />".join(line or "&nbsp;" for line in quality_notes.splitlines())
    analysis_html = "<br />".join(line or "&nbsp;" for line in analysis_notes.splitlines())

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

    scenario_section = build_scenario_rows(scenario_data)

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
        .quality-box {{
            background: #fff7ed;
            border: 1px solid #fed7aa;
            color: #9a3412;
            padding: 16px;
            border-radius: 12px;
            line-height: 1.6;
            margin-top: 12px;
        }}
        .scenario-table th {{
            background: #0f172a;
        }}
        .scenario-base {{
            background: #ecfccb;
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
        <section class="quality-section">
            <h2 class="section-title">AI 分析与投资建议</h2>
            <div class="quality-box">{analysis_html}</div>
        </section>
        <section class="quality-section">
            <h2 class="section-title">数据质量与风险提示</h2>
            <div class="quality-box">{quality_html}</div>
        </section>
        <section class="scenario-section">
            <h2 class="section-title">情景对比</h2>
            {scenario_section}
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


def generate_report(
    output_path: Path = DEFAULT_OUTPUT,
    quality_text: Optional[str] = None,
    scenario_data: Optional[dict] = None,
    analysis_text: Optional[str] = None,
    open_browser: bool = False,
) -> Path:
    portfolio_df, _ = load_positions_and_prices()
    metrics = compute_metrics(portfolio_df)
    html = build_html(
        metrics,
        quality_text=quality_text,
        scenario_data=scenario_data,
        analysis_text=analysis_text,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"报告已生成: {output_path.resolve()}")
    if open_browser:
        webbrowser.open(output_path.resolve().as_uri())
    return output_path


def main():
    parser = argparse.ArgumentParser(description="生成组合盈亏的网页报告")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="HTML 报告输出路径")
    parser.add_argument("--open", action="store_true", help="生成后在默认浏览器中打开")
    parser.add_argument("--quality-text", help="直接传入数据质量与风险提示内容")
    parser.add_argument("--quality-file", type=Path, help="从文件读取数据质量提示内容")
    parser.add_argument("--scenario-file", type=Path, help="从 JSON 文件读取情景模拟结果")
    args = parser.parse_args()

    quality_text = args.quality_text
    if quality_text is None and args.quality_file:
        quality_text = args.quality_file.read_text(encoding="utf-8")

    scenario_data: Optional[dict] = None
    if args.scenario_file and args.scenario_file.exists():
        scenario_data = json.loads(args.scenario_file.read_text(encoding="utf-8"))

    generate_report(
        output_path=args.output,
        quality_text=quality_text,
        scenario_data=scenario_data,
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
