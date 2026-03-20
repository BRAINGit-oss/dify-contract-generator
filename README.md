# Dify 合同生成服务

## 文件说明
- `app.py`：企业安全增强版 FastAPI 服务
- `dify_contract_generator.dsl.yml`：可导入 Dify 的工作流 DSL（已含鉴权头变量）
- `测试合同模板.docx`：测试合同模板
- `数据模板.xlsx`：测试数据模板

## 一、启动前准备
### 1) 创建并安装依赖
```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2) 配置环境变量（生产必填）
```powershell
$env:API_TOKEN="replace-with-strong-token"
$env:SIGNING_SECRET="replace-with-strong-signing-secret"
$env:PUBLIC_BASE_URL="https://your-domain.com"
```

### 3) 可选安全与容量参数
```powershell
$env:MAX_EXCEL_BYTES="10485760"
$env:MAX_TEMPLATE_BYTES="5242880"
$env:MAX_ROWS="500"
$env:MAX_COLUMNS="100"
$env:MAX_OUTPUT_FILES="500"
$env:DOWNLOAD_TTL_SECONDS="900"
$env:OUTPUT_RETENTION_SECONDS="86400"
$env:RATE_LIMIT_WINDOW_SECONDS="60"
$env:RATE_LIMIT_REQUESTS="20"
$env:STRICT_COLUMNS="true"
$env:ALLOWED_COLUMNS="contract_no,party_a,party_b,customer_name,customer_address,sign_date,amount,tax_rate,amount_with_tax,payment_terms,remark"
```

## 二、运行服务
```bash
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

## 三、接口测试手册
### 1) 健康检查
```bash
curl http://127.0.0.1:8000/health
```

### 2) 生成合同（本地测试）
```bash
curl -X POST "http://127.0.0.1:8000/generate-contracts" ^
  -H "Authorization: Bearer replace-with-strong-token" ^
  -H "X-Tenant-ID: finance-dept" ^
  -F "excel_file=@数据模板.xlsx" ^
  -F "template_file=@测试合同模板.docx" ^
  -F "output_format=docx"
```

返回 JSON 中会带：
- `batch_id`
- `files[].download_url`（签名下载地址）
- `files[].expires_at`

### 3) 下载合同
- 直接访问返回值里的 `download_url` 即可。
- 若超时会返回 `Download URL expired`，重新调用生成接口获取新链接。

### 4) 失败测试建议
- 去掉 `Authorization`：应返回 401
- 错误 token：应返回 401
- 超限 Excel 行数：应返回 400
- 超大文件：应返回 413

## 四、Dify 工作流接入
### 1) 导入 DSL
- 导入 `dify_contract_generator.dsl.yml`

### 2) 开始节点输入
- `生成服务地址`：`https://你的公网域名/generate-contracts`
- `API访问令牌`：与服务端 `API_TOKEN` 一致
- `租户ID`：例如 `finance-dept`

### 3) HTTP 节点头（DSL 已内置）
- `Authorization: Bearer {{api_token}}`
- `X-Tenant-ID: {{tenant_id}}`

## 五、Render 部署（可选）
1. 推送代码到 GitHub
2. Render 创建 Web Service（或使用 Blueprint）
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. 在 Render 环境变量中配置 `API_TOKEN`、`SIGNING_SECRET`、`PUBLIC_BASE_URL`

## 六、生产建议
- Dify 与服务优先放同一私网/VPC
- 网关/WAF 限制来源 IP 与请求速率
- 使用企业 KMS 管理密钥并定期轮换
- 对日志做脱敏并保留审计记录
