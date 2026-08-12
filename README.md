# SipPilot 饮航

> Self-service ordering, payment & store fulfillment platform  
> 自助点单、收付款与门店人工履约平台

荷兰饮品店自助点餐、收款与人工履约平台，形态类似 McDonald's / KFC 自助点餐终端。当前已完成 **Phase 5：Commercial Device UI**：后端交易闭环、Kiosk、KDS、Admin 三套业务前端，以及面向商用设备的触屏、状态恢复、视觉层级和安全边界均已实现。

## 已实现范围

- Windows 优先，默认 `NL / EUR / nl-NL / Europe/Amsterdam`。
- 58 张 SQLAlchemy 业务表与可往返的 Alembic 初始迁移，开发使用 SQLite，生产目标为 PostgreSQL。
- Tenant、法人、门店、Kiosk、人工制作工位、KDS Endpoint 与支付终端绑定。
- Argon2id、短期 JWT、实时账号失效、按门店收窄的 RBAC、设备凭证，以及持久化登录锁定与密码校验并发保护。
- 多语言商品、规格、门店可售状态、版本化价格表、促销与数据驱动 VAT 规则。
- 以整数欧分计算的权威 Quote、不可变订单快照、幂等订单创建与连续取餐号。
- PSP 中立的支付/退款状态机，明确保留 `UNKNOWN`，仅提供开发用 Mock Provider。
- 付款确认、订单确认、Kitchen Ticket、交易收据、审计和 Outbox 的单事务释放。
- KDS 心跳、人工制作状态机、无法履约后的 Manual Review，以及人工决定退款、重做或替代品。
- 收据完整性校验、退款收据、运营报表、支付对账视图和追加式审计记录。
- Kiosk：设备配对、菜单与规格、购物车、权威 Quote、幂等订单、支付执行/对账/重试、取餐号和脱敏收据。
- KDS：设备心跳、员工登录、队列轮询、人工制作状态机、失败原因与人工审核说明。
- Admin：按权限导航的门店策略、员工、商品定价、订单、退款、人工审核、运营报表和审计控制台。
- Phase 5：Kiosk 崩溃/刷新支付恢复、营业状态与心跳门禁；KDS 高对比三列制作看板；Admin 商用运营界面；三端 CSP、远程 HTTPS 限制与响应式设备布局。

本项目不包含自动饮品机、泵、阀、PLC、Serial、MQTT、Modbus 或任何自动制作控制。付款后由员工人工制作；支付终端和可选打印机只是点单收款外设。

真实 Adyen、Stripe 或 SumUp 凭证、网络调用、Webhook 和结算文件尚未接入。当前 Mock Provider 只能用于开发测试，生产配置会拒绝启用它。

## 目录边界

- `apps/edge-api`：当前 Phase 3 的 FastAPI 交易后端。
- `apps/kiosk-web`：顾客自助点餐、支付与收据前端。
- `apps/kitchen-display-web`：员工人工制作队列与异常上报看板。
- `apps/admin-web`：管理、审核、退款与报表控制台。
- `apps/edge-worker`：后续 Outbox/可靠任务进程边界，当前未实现派发器。
- `apps/windows-agent`：后续 Windows 服务看护与更新边界，不负责饮品制作设备。
- `packages`：共享契约、API Client 与多语言资源边界。

## 运行环境

- Windows 10/11
- PowerShell 5.1+
- Node.js 24 / npm 11
- Python 3.12（推荐；开发兼容 3.13）
- Docker Desktop 可选，仅用于开发 PostgreSQL；商业设备不依赖 Docker Desktop

## 最快体验：Windows 一键演示

第一次运行时，直接双击项目根目录的 `Start-Demo.cmd`。脚本会：

1. 检查并在需要时调用 Bootstrap 安装依赖。
2. 幂等升级独立演示 SQLite schema，并确认 Alembic 已到最新 revision。
3. 在独立的 `var/demo/demo.db` 中创建或严格校验一套本机演示门店、6 个饮品、9% VAT、价格表、Kiosk、KDS 与 Mock 支付终端。
4. 显示 Kiosk/KDS/Admin 所需的本机演示凭据。
5. 启动 Backend 与三套前端，并在服务就绪后打开浏览器。

也可以在项目根目录的 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\demo.ps1
```

演示顺序：先在 Kitchen Display 中连接并保持页面开启，再在 Kiosk 点单，最后可在 Admin 查看订单与运营数据。默认地址：

- Kitchen Display: http://127.0.0.1:5174
- Kiosk: http://127.0.0.1:5173
- Admin: http://127.0.0.1:5175
- OpenAPI: http://127.0.0.1:8000/docs

固定本机演示账号为 `demo-nl / demo-owner / DemoOwner!2026-NL`；Kiosk ID 和 KDS Endpoint ID 由启动窗口输出。启动器使用独立、Git 已忽略的 `var/demo/demo.db`，不会污染日常开发数据库 `var/dev.db`。这些固定凭据、开发 JWT 和 Mock 支付都只适合本机演示，严禁复制到生产设备、试点配置或工单中。完整操作见 [一键演示指南](./docs/runbooks/demo.md)。

## 首次初始化

在包含 `README.md` 和 `scripts` 的项目根目录打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\bootstrap.ps1
```

脚本会创建 `.env` 和 `.venv`、安装 Python/npm 依赖，并把本地数据库升级到最新 Alembic revision。执行策略只对当前 PowerShell 窗口有效。

## 创建第一家门店

依赖和迁移完成后执行一次：

```powershell
.\.venv\Scripts\python.exe -m app.cli bootstrap-store `
  --tenant-code demo `
  --tenant-name "Demo Drinks" `
  --legal-entity-code demo-nl `
  --legal-entity-name "Demo Drinks B.V." `
  --store-code AMS01 `
  --store-name "Amsterdam Store" `
  --owner-username owner `
  --owner-display-name "Store Owner"
```

密码会在终端中隐藏输入并要求二次确认。成功输出的 `kiosk_key` 和 `fulfillment_endpoint_key` 只显示这一次，数据库只保存哈希；请按秘密凭证保存，不要提交到 Git、日志或截图中。Bootstrap 默认保持 `accepting_orders=false`，必须在 KDS 在线且人工确认后再由管理接口开放接单。

## 启动全部应用

```powershell
.\scripts\dev.ps1
```

`dev.ps1` 会先幂等执行 `alembic upgrade head`，再启动：

- Kiosk: http://127.0.0.1:5173
- Kitchen Display: http://127.0.0.1:5174
- Admin: http://127.0.0.1:5175
- Edge API: http://127.0.0.1:8000
- OpenAPI: http://127.0.0.1:8000/docs

三套前端首次打开时通过运行时界面接收 API 地址及所需凭据；任何 `VITE_*` 变量都只能保存非秘密 API 地址。开发阶段凭据只保存在当前浏览器会话，商业 Windows 设备必须由后续 Windows Agent 从受保护的系统存储注入。
OpenAPI、Swagger UI 和 ReDoc 只在 `development` / `test` 开启；`staging` / `production` 默认不发布这些入口。

## 质量检查

```powershell
.\scripts\check.ps1
.\scripts\dev.ps1 -StartupCheck
```

第一条运行 Python 格式、Lint、Mypy、Pytest，以及三个前端的格式、Lint、类型、测试与生产构建。第二条验证四个开发服务能够启动、响应并释放端口。

## 可选 PostgreSQL

默认 SQLite 适合单机开发和测试。验证 PostgreSQL 时：

```powershell
docker compose --profile postgres up -d postgres
```

把 `.env` 的 `DATABASE_URL` 改为 `.env.example` 中的 PostgreSQL 示例，然后重新执行：

```powershell
.\.venv\Scripts\python.exe -m alembic -c .\apps\edge-api\alembic.ini upgrade head
```

不要把运行数据库放在 OneDrive、SMB 或其他同步目录中。

## 常见启动问题

- `无法识别 .\scripts\bootstrap.ps1`：先运行 `Get-Location` 和 `Test-Path .\scripts\bootstrap.ps1`，后者必须返回 `True`。
- 执行策略询问：无需选择 `A`，使用上面的 `Set-ExecutionPolicy ... -Force`，不要永久设为 `Unrestricted`。
- 端口占用：停止旧进程，或仅在开发验收时向 `dev.ps1` 传入明确的备用端口。
- 依赖安装失败：确认 PyPI/npm 网络可用后重跑 Bootstrap，不要删除锁文件掩盖解析问题。

## 文档

- [架构设计](./ARCHITECTURE.md)
- [Phase 3 Backend 范围](./docs/phase-3-backend-scope.md)
- [Phase 4 Frontend 范围](./docs/phase-4-frontend-scope.md)
- [Phase 5 Commercial UI 范围](./docs/phase-5-ui-scope.md)
- [Phase 2 历史范围](./docs/phase-2-scope.md)
- [Adyen 选择记录](./docs/payment/adyen-selection.md)
- [Windows 开发说明](./docs/windows/development.md)
- [Windows 一键演示指南](./docs/runbooks/demo.md)
- [开发 Runbook](./docs/runbooks/development.md)

下一步应进入商业上线准备：Windows Agent/受保护设备凭据、真实 PSP 终端认证与对账、打印、部署签名、监控告警、备份恢复及现场验收。当前 Mock Payment 仍不可用于生产。
