import argparse
import json
import re
import subprocess
import sys
import threading
from typing import Dict, List, Optional

from openai import OpenAI

from portfolio_dashboard import (
    DEFAULT_OUTPUT,
    generate_report,
    load_positions_and_prices,
)


client = OpenAI(
    api_key="sk-a34b9db0d1de482f941af700ed56b320",
    base_url="https://api.deepseek.com",
)


SYSTEM_PROMPT = (
    "你是一名投研分析助手。"
    "每次沟通都要："
    "1) 主动调用 analyze_portfolio_quality 等校验工具，确认数据质量；"
    "2) 如果用户提供情景参数，则调用 simulate_scenarios 生成对应情景结果；"
    "3) 第二轮回答时，对比不同情景的风险收益拐点并输出投资建议。"
)

DEFAULT_USER_PROMPT = (
    "我正在复盘 data/portfolio_positions.xlsx 中的持仓表现，"
    "请你自主决定需要读取的内容、校验方式与建议要点。"
)


TOOL_BLOCK_PATTERN = re.compile(r"<｜tool.*?begin｜>.*?<｜tool.*?end｜>", re.DOTALL)
TOOL_TAG_PATTERN = re.compile(r"<｜tool.*?｜>")


def normalize_cli_tokens(argv: List[str]) -> List[str]:
    normalized: List[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("-s", "--scenario"):
            if i + 1 >= len(argv):
                normalized.append(token)
            else:
                value = argv[i + 1]
                normalized.append(f"--scenario={value}")
                i += 1
        else:
            normalized.append(token)
        i += 1
    return normalized


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MCP Host CLI")
    parser.add_argument(
        "-s",
        "--scenario",
        action="append",
        dest="scenario_values",
        help="情景价格调整，例如 -5%%, 0%%, +5%% 表示百分比，或 2 表示绝对价格 +2",
    )
    normalized = normalize_cli_tokens(sys.argv[1:])
    return parser.parse_args(normalized)


def parse_scenario_specs(values: Optional[List[str]]) -> List[Dict[str, float]]:
    specs: List[Dict[str, float]] = []
    if not values:
        return specs

    for raw in values:
        token = raw.strip()
        if not token:
            continue
        label = token
        pct = 0.0
        delta = 0.0
        if token.endswith("%"):
            pct = float(token.rstrip("%")) / 100.0
        else:
            delta = float(token)
        specs.append({"label": label, "pct": pct, "delta": delta})
    return specs


def format_scenario_instruction(specs: List[Dict[str, float]]) -> str:
    labels = ", ".join(spec["label"] for spec in specs)
    return (
        f"情景参数：{labels}。"
        "请在调用 simulate_scenarios 工具时将这些调整注入 adjustments 字段，"
        "百分比代表基于当前价格的涨跌，纯数字代表绝对价格调整。"
    )


def prompt_user_query() -> str:
    try:
        user_text = input("请输入你想了解的组合问题（直接回车使用默认）：").strip()
    except EOFError:
        user_text = ""

    return user_text or DEFAULT_USER_PROMPT


def read_stderr(proc: subprocess.Popen) -> None:
    for line in proc.stderr:
        print("SERVER STDERR:", line.strip())


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-u", "server/mcp_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=".",
    )
    threading.Thread(target=read_stderr, args=(proc,), daemon=True).start()
    return proc


def build_tool_payload() -> tuple[List[dict], Dict[str, float]]:
    positions_df, price_df = load_positions_and_prices()
    rows = positions_df.to_dict(orient="records")
    price_map: Dict[str, float] = {}
    for _, row in price_df.iterrows():
        value = row.get("price")
        if value is None or value != value:  # skip None/NaN
            continue
        price_map[str(row["symbol"]).upper()] = float(value)
    return rows, price_map


def format_quality_summary(result_payload: dict) -> str:
    quality_summary = None
    if isinstance(result_payload, dict):
        quality_summary = result_payload.get("summary")
        if not quality_summary:
            warnings = result_payload.get("warnings") or []
            if warnings:
                quality_summary = "；".join(warnings)
    return quality_summary or json.dumps(result_payload, ensure_ascii=False)


def summarize_scenarios(payload: Optional[dict]) -> str:
    if not payload:
        return "暂无情景结果。"

    lines = ["情景对比："]
    scenarios = payload.get("scenarios") or []
    for item in scenarios:
        totals = item.get("totals") or {}
        label = item.get("label")
        pnl = totals.get("pnl")
        pnl_pct = totals.get("pnl_pct")
        lines.append(
            f"- {label}: 净盈亏 {pnl:.2f}，净盈亏% {pnl_pct:.2%}" if pnl is not None else f"- {label}: 未能计算结果"
        )
    return "\n".join(lines)


def run_fallback_mcp(proc: subprocess.Popen, scenario_specs: List[Dict[str, float]]):
    print("\n模型未触发 MCP 工具，主动调用关键工具以突出 MCP 作用…")
    try:
        rows, price_map = build_tool_payload()
    except Exception as exc:
        print(f"准备组合数据失败：{exc}")
        return None, None

    quality_result = call_tool(proc, "analyze_portfolio_quality", {"rows": rows, "price_map": price_map})
    quality_payload = quality_result.get("result", quality_result)
    quality_summary = format_quality_summary(quality_payload)

    adjustments = scenario_specs or [
        {"label": "-5%", "pct": -0.05, "delta": 0.0},
        {"label": "+5%", "pct": 0.05, "delta": 0.0},
    ]
    scenario_result = call_tool(
        proc,
        "simulate_scenarios",
        {"rows": rows, "price_map": price_map, "adjustments": adjustments},
    )
    scenario_payload = scenario_result.get("result", scenario_result)

    fallback_answer = (
        f"数据质量与风险提示：\n{quality_summary}\n\n"
        f"{summarize_scenarios(scenario_payload)}"
    )
    print(fallback_answer)
    update_report(
        quality_summary or "暂无模型提示。",
        scenario_payload,
        analysis_text=fallback_answer,
    )
    return quality_summary, scenario_payload


def call_tool(proc: subprocess.Popen, name: str, args: dict) -> dict:
    req = {
        "type": "tool",
        "name": name,
        "arguments": args,
    }
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()

    line = proc.stdout.readline().strip()
    return json.loads(line)


def print_tool_list(tools: List[dict]) -> None:
    print("Server Tools Loaded:")
    for t in tools:
        print(" -", t["function"]["name"])


def update_report(
    quality_text: str,
    scenario_data: Optional[dict],
    analysis_text: Optional[str] = None,
) -> None:
    try:
        generate_report(
            output_path=DEFAULT_OUTPUT,
            quality_text=quality_text,
            scenario_data=scenario_data,
            analysis_text=analysis_text,
        )
    except Exception as exc:
        print(f"生成网页报告失败：{exc}")


def strip_tool_markup(text: str) -> str:
    if not text:
        return ""
    cleaned = TOOL_BLOCK_PATTERN.sub("", text)
    cleaned = TOOL_TAG_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("▁", " ")
    return cleaned.strip()


def main():
    args = parse_cli_args()
    scenario_specs = parse_scenario_specs(args.scenario_values)
    user_query = prompt_user_query()
    if scenario_specs:
        user_query = f"{user_query}\n\n{format_scenario_instruction(scenario_specs)}"

    print("启动 MCP Server ...")
    proc = start_server()

    try:
        init_line = proc.stdout.readline().strip()
        if not init_line:
            print("Server 没有输出初始化信息")
            return

        init = json.loads(init_line)
        tools = init["tools"]
        print_tool_list(tools)

        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]

        print("\n向 DeepSeek 发起第一次调用（工具选择）...")
        resp1 = client.chat.completions.create(
            model="deepseek-chat",
            messages=base_messages,
            tools=tools,
        )

        msg = resp1.choices[0].message
        tool_calls = msg.tool_calls or []
        tool_messages = []
        scenario_payload = None
        quality_summary = None

        for call in tool_calls:
            tool_name = call.function.name
            args_dict = json.loads(call.function.arguments)
            print(f"\n模型决定调用工具：{tool_name}({args_dict})")
            tool_result = call_tool(proc, tool_name, args_dict)
            print("工具执行成功，结果：", tool_result)
            result_payload = tool_result.get("result", tool_result)

            if tool_name == "simulate_scenarios":
                scenario_payload = result_payload
            if tool_name == "analyze_portfolio_quality":
                quality_summary = format_quality_summary(result_payload)

            tool_messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result_payload, ensure_ascii=False),
            })

        if not tool_messages:
            quality_summary, scenario_payload = run_fallback_mcp(proc, scenario_specs)
            if quality_summary is not None:
                return
            print("\n模型未调用任何工具且备选方案失败。")
            final_answer = msg.content or ""
            print(final_answer)
            clean_answer = strip_tool_markup(final_answer)
            update_report(clean_answer or "暂无模型提示。", None, analysis_text=clean_answer)
            return

        print("\n向 DeepSeek 发起第二次总结调用...")
        second_messages = base_messages + [msg] + tool_messages
        resp2 = client.chat.completions.create(
            model="deepseek-chat",
            messages=second_messages,
        )
        final_answer = resp2.choices[0].message.content or ""
        print("\n最终回答：")
        print(final_answer)
        quality_text = strip_tool_markup(quality_summary or final_answer)
        final_analysis = strip_tool_markup(final_answer)
        update_report(
            quality_text or "暂无模型提示。",
            scenario_payload,
            analysis_text=final_analysis or quality_text,
        )

    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
