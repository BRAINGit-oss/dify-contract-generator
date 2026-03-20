# Dify 合同生成服务

## 文件说明
- `app.py`：FastAPI 服务，提供 `/generate-contracts`、`/download/{batch_id}/{file_name}`、`/health`
- `dify_contract_generator.dsl.yml`：可导入 Dify 的工作流 DSL
- `测试合同模板.docx`：测试合同模板
- `数据模板.xlsx`：测试数据模板

## 本地运行
```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

## Render 一键部署
1. 将本项目上传到 GitHub 公共仓库
2. 打开 Render 新建 Web Service 或使用 Blueprint
3. 运行命令：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. 部署后会获得公网 HTTPS 地址

## Dify 配置
- 在工作流输入变量 `生成服务地址(generator_url)` 填写：
  - `https://你的公网域名/generate-contracts`
