# 投资组合报告生成器

本仓库包含一个基于 Pandas 的小型工具，可将 `data/` 目录中的持仓与价格文件转换成带有情景分析、数据质量提示以及 AI 投资建议的 HTML 报告。本文档介绍如何配置环境与使用新增的 `--analysis-text/--analysis-file` 选项。

## 1. 准备运行环境
1. 安装 Python 3.10+。
2. 安装依赖（至少需要 `pandas` 与 `openpyxl` 才能读取 Excel）：
   ```bash
   pip install pandas openpyxl
   ```

## 2. 准备数据文件
| 路径 | 内容 |
|------|------|
| `data/portfolio_positions.xlsx` | **推荐**。包含 `positions` 与 `price_map` 两个 sheet。`positions` 需具备 `symbol`, `qty`, `cost` 列；`price_map` 需要 `symbol`, `price` 列。 |
| `data/portfolio_positions.csv` | 仅当没有 Excel 文件时使用，需包含 `symbol`, `qty`, `cost`, `price` 列。 |

> 如果两个文件都存在，程序优先读取 Excel。

## 3. 生成报告
基础命令：
```bash
python host/portfolio_dashboard.py --output reports/latest.html --open
```

- `--output`：指定 HTML 产物路径（默认 `reports/portfolio_report.html`）。
- `--open`：生成后立即在系统默认浏览器中打开。

## 4. 传入 AI 投资建议
更新后的脚本提供两种方式注入 AI 文本：

1. **直接传字符串**
   ```bash
   python host/portfolio_dashboard.py \
       --analysis-text "短期建议减仓科技股，关注医药板块的防御属性。"
   ```
2. **从文件读取**
   ```bash
   python host/portfolio_dashboard.py \
       --analysis-file reports/ai_summary.txt
   ```
   若文件不存在或为空，则会自动回退到程序自带的盈亏分析描述。

## 5. 其他可选输入
- `--quality-text / --quality-file`：传入数据质量与风险提示。
- `--scenario-file path/to/scenario.json`：提供情景模拟 JSON，结构示例：
  ```json
  {
    "base_totals": {"pnl": 120000},
    "scenarios": [
      {"label": "乐观", "totals": {"pnl": 180000, "pnl_pct": 12.3}},
      {"label": "压力", "totals": {"pnl": -90000, "pnl_pct": -6.1}}
    ]
  }
  ```

将上述参数自由组合即可生成带有 AI 建议的完整报告。若未提供 AI 文本，程序会根据持仓胜负、净值与情景模拟自动生成一段中文分析，确保报告始终可读。
