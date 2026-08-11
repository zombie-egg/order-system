# Netherlands Drink Kiosk Platform

荷兰饮品店自助点餐、收款与人工履约平台，形态类似 McDonald's / KFC 的自助点餐终端。当前仓库处于 **Phase 2：工程骨架**。

## 当前范围

- Windows 优先。
- Kiosk、Kitchen Display、Admin 三个独立 React 应用。
- FastAPI Edge API，只包含健康检查、版本和 OpenAPI 技术端点。
- 荷兰默认配置：`NL / EUR / nl-NL / Europe/Amsterdam`。
- 首选支付方向：Adyen S1U2 + Terminal API。
- 付款后由员工人工制作；无法履约进入人工审核。
- 不包含自动饮品机、Serial、MQTT、Modbus 或任何机器控制。
- 支付终端和可选小票打印机属于收付款外设，不代表系统会连接或控制饮品制作设备。

本阶段没有商品、购物车、订单、支付、退款、KDS 状态机或后台业务功能。

## 目录边界

- `apps/kiosk-web`：顾客自助点餐界面骨架。
- `apps/kitchen-display-web`：员工人工接单与制作看板骨架。
- `apps/admin-web`：管理与人工审核界面骨架。
- `apps/edge-api`：仅含健康检查、版本和 OpenAPI 的 FastAPI 技术骨架。
- `apps/edge-worker`：为后续可靠任务处理预留的进程边界，本阶段没有实现。
- `apps/windows-agent`：为后续 Windows 进程看护、日志和更新预留，不负责饮品制作设备控制。
- `packages`：共享契约、API Client 和多语言资源的预留边界。
- `simulators/payment-simulator`：后续支付状态测试预留；不是饮品机或硬件制作模拟器。

## 运行环境

- Windows 10/11
- Node.js 24
- npm 11
- Python 3.12（推荐；开发环境兼容 3.13）
- Docker Desktop 可选，仅用于开发 PostgreSQL；商业设备不依赖 Docker Desktop

## 首次初始化

先进入包含 `README.md` 和 `scripts` 文件夹的项目根目录，再在 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\bootstrap.ps1
```

`-Scope Process` 只对当前 PowerShell 窗口生效，关闭窗口后自动恢复；`-Force` 用于避免再次出现执行策略确认提示。

脚本会：

1. 复制 `.env.example` 为本地 `.env`（若尚不存在）。
2. 创建 `.venv`。
3. 安装 Python 和 npm 依赖。

## 启动全部应用

确认当前 PowerShell 仍位于项目根目录，然后运行：

```powershell
.\scripts\dev.ps1
```

默认地址：

- Kiosk: http://localhost:5173
- Kitchen Display: http://localhost:5174
- Admin: http://localhost:5175
- Edge API: http://127.0.0.1:8000
- OpenAPI: http://127.0.0.1:8000/docs

如果 PowerShell 虚拟环境激活失败，可以直接使用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\edge-api --reload
```

## 质量检查

```powershell
.\scripts\check.ps1
```

检查包括前端格式、Lint、TypeScript、测试、构建，以及 Python Ruff、Mypy 和 Pytest。

如需验证四个服务能否真正启动、响应 HTTP 并在测试后释放端口，可运行：

```powershell
.\scripts\dev.ps1 -StartupCheck
```

该命令只做启动验收，不会让服务持续驻留。

## 常见启动问题

- 如果提示无法识别 `.\scripts\bootstrap.ps1` 或 `.\scripts\dev.ps1`，先运行 `Get-Location`；当前目录必须是本项目根目录，而不是 `C:\Users\<用户名>`。
- 可以运行 `Test-Path .\scripts\bootstrap.ps1` 检查位置；返回 `True` 后再执行脚本。
- 执行策略提示无需选择 `A`。直接使用上面的 `Set-ExecutionPolicy ... -Force`，且不要把策略永久改为 `Unrestricted`。

## 可选 PostgreSQL

本地开发默认使用嵌入式 SQLite，仅用于技术就绪检查，不包含任何业务表，也不需要单独安装数据库服务。需要验证 PostgreSQL 连接时：

```powershell
docker compose --profile postgres up -d postgres
```

然后将本地 `.env` 的 `DATABASE_URL` 改为 `.env.example` 中给出的 PostgreSQL 示例。

## 文档

- [架构设计](./ARCHITECTURE.md)
- [Phase 2 范围](./docs/phase-2-scope.md)
- [Adyen 选择记录](./docs/payment/adyen-selection.md)
- [Windows 开发说明](./docs/windows/development.md)
- [ADR](./docs/adr/)

## 下一阶段

Phase 3 才开始 Backend 业务开发。任何业务实现都应先满足架构中的幂等、不可变订单快照、支付 `UNKNOWN` 状态、Kitchen Ticket 和 Manual Review 约束。
