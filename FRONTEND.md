# 本地前端启动

这个前端使用 Flask，入口文件是 `ops_frontend.py`。

## 启动

```powershell
$env:PYTHONPATH="src"
python ops_frontend.py
```

打开：

```text
http://127.0.0.1:5050
```

## 当前页面

- 投诉登记 Agent：上传投诉 Excel，生成投诉登记明细、分类汇总、良品/疑似良品、不良品、人工复核清单。
- 销售分析 Agent：上传销售 Excel，生成日销报告、优惠券申请清单、达人素材需求、高风险商品清单和 Markdown 日报摘要。

所有输出文件保存在 `data/output/`，原始上传文件保存在 `data/raw/`，运行记录和决策留痕保存在 `data/processed/ecom_ops.sqlite3`。
