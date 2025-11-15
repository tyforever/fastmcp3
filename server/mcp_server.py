import sys
import os
import json
import traceback

# 使 Python 能找到 tools/ 目录
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from tools.file_tools import register_file_tools
from tools.csv_tools import register_csv_tools
from tools.excel_tools import register_excel_tools
from tools.invest_tools import register_invest_tools


TOOLS = {}

def register_tools():
    """收集全部工具"""
    TOOLS.update(register_file_tools())
    TOOLS.update(register_csv_tools())
    TOOLS.update(register_excel_tools())
    TOOLS.update(register_invest_tools())


def main():
    register_tools()

    # 初始化输出（模型用来识别工具）
    print(json.dumps({
    "type": "mcp_initialized",
    "tools": [
        {
            "type": "function",
            "function": {
                "name": k,
                "description": v["description"],
                "parameters": {
                    "type": "object",
                    "properties": v["parameters"],
                    "required": ["path"]

                }
            }
        }
        for k, v in TOOLS.items()
    ],
}), flush=True)


    # 主循环（接受 host 的 JSON 输入）
    for line in sys.stdin:
        try:
            if not line.strip():
                continue

            req = json.loads(line)

            if req["type"] == "tool":
                name = req["name"]
                args = req.get("arguments", {})

                if name not in TOOLS:
                    resp = {
                        "type": "error",
                        "error": f"Unknown tool: {name}",
                    }
                else:
                    func = TOOLS[name]["callable"]
                    try:
                        result = func(**args)
                        resp = {
                            "type": "tool_result",
                            "name": name,
                            "result": result,
                        }
                    except Exception as e:
                        resp = {
                            "type": "error",
                            "error": str(e),
                            "trace": traceback.format_exc(),
                        }

                print(json.dumps(resp), flush=True)

        except Exception as e:
            print(json.dumps({
                "type": "error",
                "error": str(e),
                "trace": traceback.format_exc(),
            }), flush=True)


if __name__ == "__main__":
    main()
