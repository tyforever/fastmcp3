import os
import base64

def read_file(path: str, encoding: str = None):
    """
    自动读取文本或二进制文件。
    - 尝试 UTF-8
    - 失败后检查 BOM
    - 再失败则 fallback latin-1
    - encoding="binary" 则返回 base64
    """

    # binary 读取
    if encoding == "binary":
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    # 没有指定 encoding → 模型自动调用
    if encoding is None:
        # 1) 尝试 UTF-8
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except:
            pass

        # 2) 检测 BOM
        with open(path, "rb") as f:
            raw = f.read()

        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            return raw.decode("utf-16", errors="replace")

        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig", errors="replace")

        # 3) fallback latin1（最保底）
        return raw.decode("latin-1", errors="replace")

    # 指定 encoding 读取
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode(encoding, errors="replace")


def list_files(dir: str):
    return os.listdir(dir)


def register_file_tools():
    return {
        "read_file": {
            "description": "读取文件内容",
            "parameters": {
                "path": {"type": "string"},
                "encoding": {"type": "string"},
            },
            "callable": read_file,
        },
        "list_files": {
            "description": "列出目录文件",
            "parameters": {
                "dir": {"type": "string"},
            },
            "callable": list_files,
        },
    }
