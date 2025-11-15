try:
    import openpyxl
except ImportError:
    openpyxl = None


def read_excel(path: str):
    if openpyxl is None:
        raise RuntimeError("openpyxl 未安装，请执行: uv pip install openpyxl")

    wb = openpyxl.load_workbook(path)
    sheet = wb.active

    return [
        [cell.value for cell in row]
        for row in sheet.iter_rows()
    ]


def register_excel_tools():
    return {
        "read_excel": {
            "description": "读取 Excel 文件",
            "parameters": {
                "path": {"type": "string"},
            },
            "callable": read_excel,
        }
    }
