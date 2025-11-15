import csv

def read_csv(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.reader(f))


def register_csv_tools():
    return {
        "read_csv": {
            "description": "读取 CSV 文件",
            "parameters": {
                "path": {"type": "string"}
            },
            "callable": read_csv,
        },
    }
