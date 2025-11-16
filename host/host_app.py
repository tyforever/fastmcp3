import json
import subprocess
import threading

from openai import OpenAI


# =============================
# 配置 DeepSeek API
# =============================
client = OpenAI(
    api_key="sk-a34b9db0d1de482f941af700ed56b320",
    base_url="https://api.deepseek.com",
)


# =============================
# 打印 server 的 stderr（调试）
# =============================
def read_stderr(proc):
    for line in proc.stderr:
        print("SERVER STDERR:", line.strip())


# =============================
# 启动 MCP Server
# =============================
def start_server():
    proc = subprocess.Popen(
        [r".\.venv\Scripts\python.exe", "-u", "server/mcp_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=".",
    )
    threading.Thread(target=read_stderr, args=(proc,), daemon=True).start()
    return proc


# =============================
# 调用本地工具
# =============================
def call_tool(proc, name, args):
    req = {
        "type": "tool",
        "name": name,
        "arguments": args,
    }
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()

    line = proc.stdout.readline().strip()
    return json.loads(line)


# =============================
# 主流程
# =============================
def main():
    print("启动 MCP Server ...")
    proc = start_server()

    # ------------------------
    # 读取初始化信息
    # ------------------------
    init_line = proc.stdout.readline().strip()
    if not init_line:
        print("Server 没有输出初始化信息")
        proc.terminate()
        return

    init = json.loads(init_line)
    tools = init["tools"]

    print("Server Tools Loaded:")
    for t in tools:
        print(" -", t["function"]["name"])

    # ------------------------
    # 用户请求
    # ------------------------
    user_query = (
        "我有一个 Excel 文件 data/portfolio_positions.xlsx，其中 positions 工作表"
        "包含 symbol/qty/cost，price_map 工作表包含最新 price。"
        "请先读取 Excel，必要时读取 CSV data/portfolio_positions.csv，"
        "然后计算每个持仓和整个组合的盈亏、净盈亏百分比，并按多/空拆分。"
        "最后输出结构化结论和投资建议。"
    )

    print("\n向 DeepSeek 发起第一次调用...")

    # ------------------------
    # 第一次模型调用（模型选择工具）
    # ------------------------
    resp1 = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": user_query}],
        tools=tools,
    )

    msg = resp1.choices[0].message
    tool_calls = msg.tool_calls

    # ------------------------
    # 模型决定调用工具
    # ------------------------
    if tool_calls:
        call = tool_calls[0]

        tool_name = call.function.name
        args = json.loads(call.function.arguments)
        tool_call_id = call.id

        print(f"\n模型决定调用工具：{tool_name}({args})")

        # 执行工具
        tool_result = call_tool(proc, tool_name, args)

        print("工具执行成功，结果：", tool_result)

        print("\n向 DeepSeek 发起第二次总结调用...")

        # 第二次调用模型（总结）
        resp2 = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": user_query},
                msg,
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                },
            ],
        )

        print("\n最终回答：")
        print(resp2.choices[0].message.content)

    else:
        print("\n模型未调用任何工具：")
        print(msg.content)

    proc.terminate()


# =============================
if __name__ == "__main__":
    main()
