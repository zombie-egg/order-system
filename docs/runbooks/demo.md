# Windows 一键演示

本指南用于在一台 Windows 开发电脑上操作完整的本机演示：Backend、顾客 Kiosk、人工制作 KDS 和 Admin 共用一套独立的 SQLite 演示数据库。

## 启动

最简单的方法是在项目根目录双击 `Start-Demo.cmd`。双击入口已经为本次进程使用 `ExecutionPolicy Bypass`，不会永久修改 Windows 执行策略，也不需要在询问中手动输入 `A`。

如果更习惯 PowerShell，请先确认当前目录中能看到 `README.md` 和 `scripts`，然后运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\demo.ps1
```

第一次启动可能需要从 PyPI 和 npm 下载依赖，时间会比后续启动长。启动器随后会：

1. 检查 Python、Node.js、npm 和项目依赖；缺失时调用 `bootstrap.ps1` 修复。
2. 在 `var/demo/demo.db` 创建或升级专用演示数据库，并验证 Alembic 已到最新 revision。
3. 调用 Backend 的 `seed-demo` 命令创建或严格校验演示门店、6 个饮品、9% VAT、价格表、Kiosk、KDS 与 Mock 支付终端。
4. 在启动窗口显示三个前端需要填写的本机演示凭据。
5. 启动 Backend 和三套前端；服务就绪后自动打开三个页面。

启动器只绑定 `127.0.0.1`，不会把开发服务暴露到局域网。保持启动窗口开启；按 `Ctrl+C` 会停止它启动的全部服务并释放端口。

如果不想自动打开浏览器：

```powershell
.\scripts\demo.ps1 -NoBrowser
```

只验证初始化、四个服务启动和端口清理：

```powershell
.\scripts\demo.ps1 -StartupCheck -NoBrowser
```

## 地址与演示账号

启动窗口会显示 Kiosk ID 和 KDS Endpoint ID。默认地址与固定的本机开发凭据为：

| 用途                    | 地址/字段    | 值                                     |
| ----------------------- | ------------ | -------------------------------------- |
| API                     | Base URL     | `http://127.0.0.1:8000/api/v1`         |
| Kitchen Display         | 页面         | `http://127.0.0.1:5174`                |
| Kitchen Display         | Endpoint ID  | 以启动窗口输出为准                     |
| Kitchen Display         | Endpoint Key | `demo-kds-key-development-only-2026`   |
| Kitchen Display / Admin | Tenant       | `demo-nl`                              |
| Kitchen Display / Admin | Username     | `demo-owner`                           |
| Kitchen Display / Admin | Password     | `DemoOwner!2026-NL`                    |
| Kiosk                   | 页面         | `http://127.0.0.1:5173`                |
| Kiosk                   | Kiosk ID     | 以启动窗口输出为准                     |
| Kiosk                   | Kiosk Key    | `demo-kiosk-key-development-only-2026` |
| Admin                   | 页面         | `http://127.0.0.1:5175`                |
| OpenAPI                 | 文档         | `http://127.0.0.1:8000/docs`           |

这些凭据被刻意固定，仅用于本机 `development` 演示；数据库中仍只保存密码和设备 Key 的哈希。不要把它们用于试点或生产设备。

## 建议操作顺序

1. 先打开 Kitchen Display，填写启动窗口中的 API、Endpoint ID、Endpoint Key、Tenant、Username 和 Password，然后点击连接。
2. 保持 Kitchen Display 页面开启。KDS 每 4 秒发送心跳；没有在线 KDS 时，Backend 会在扣款前暂停订单。
3. 打开 Kiosk，填写 API、Kiosk ID 和 Kiosk Key。选择饮品与规格，确认购物车并执行开发用 Mock 支付。
4. 回到 Kitchen Display，新订单会进入队列；依次执行接受、开始制作、完成和取餐。
5. 打开 Admin，使用同一组 Tenant、Username 和 Password 登录，查看门店策略、商品、订单、支付、报表和审计记录。

## 数据隔离与重复启动

一键演示使用 `var/demo/demo.db`，不会写入日常开发数据库 `var/dev.db`。正常重复启动不会复制演示数据，也不会删除订单。

演示端口可以通过脚本参数覆盖；启动器会把匹配的 API Base URL 注入三个 Vite 开发进程并让 `dev.ps1` 生成对应的 loopback CORS origins，因此 `-StartupCheck` 示例可安全使用备用端口。如果默认端口已被其他程序或无法访问的旧进程占用，双击启动器会自动寻找空闲备用端口并在窗口中打印最终地址。

`seed-demo` 会严格校验 Backend 管理的演示组织、商品、税率、价格、可售状态和固定凭据哈希。如果核心数据被人工改变，启动会安全失败并保留现状，不会悄悄覆盖 Admin 中的操作。

如果这是纯演示数据且确实需要重新开始，请先关闭启动窗口，备份后再移动 `var/demo/demo.db`。不要对包含试点或真实业务数据的数据库这样做。

## 安全边界

- 演示支付只使用 `MOCK`，不会连接真实银行卡、支付终端或 PSP。
- 演示 JWT、账号密码和设备 Key 都只适合本机开发，不要复制到生产配置、工单、截图或 Git。
- 浏览器只在当前 tab 的 session storage 中保存开发会话；关闭 tab 会清除会话。
- 本启动器不是生产部署方案，也不包含 Windows Kiosk Mode、Windows Agent、受保护设备密钥存储、真实支付终端认证或打印方案。

## 常见问题

### 找不到脚本

如果出现“无法识别 `.\scripts\demo.ps1`”，说明 PowerShell 不在项目根目录。运行：

```powershell
Get-Location
Test-Path .\scripts\demo.ps1
```

第二条必须返回 `True`；否则请进入包含 `README.md` 的项目目录，或直接双击 `Start-Demo.cmd`。

### 执行策略询问

无需选择 `A`。使用本文带 `-Force` 的临时命令，或直接双击 `Start-Demo.cmd`。不要永久把执行策略改为 `Unrestricted`。

### 依赖安装失败

确认 Python 3.12/3.13、Node.js 24、PyPI 和 npm 网络可用，然后重新运行：

```powershell
.\scripts\bootstrap.ps1
```

### 端口占用

先关闭旧的演示/开发窗口。隔离启动验收时也可以显式提供四个不重复端口：

```powershell
.\scripts\demo.ps1 -StartupCheck -NoBrowser `
  -ApiPort 18000 -KioskPort 15173 `
  -KitchenDisplayPort 15174 -AdminPort 15175
```

如果你显式指定端口，端口被占用时启动器会报错而不会擅自更改；可以改用备用端口：

```powershell
.\scripts\demo.ps1 -ApiPort 18000 -KioskPort 15173 `
  -KitchenDisplayPort 15174 -AdminPort 15175
```

启动器会把备用 API 地址和对应 CORS origins 同步注入 Kiosk、KDS 与 Admin，四个页面仍连接同一套演示 Backend。

### 页面打开但无法下单

先确认 Kitchen Display 已连接并显示 `Connected`。KDS 心跳超时、门店停止接单或端口上遗留的旧 Backend 都可能使 Kiosk 暂停结账。

### 查看日志

每次启动的标准输出和错误日志位于 `var/logs`。查找时间最新、名称为 `edge-api`、`kiosk`、`kitchen-display` 或 `admin` 的文件。
