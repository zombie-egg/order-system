# 部署说明（单机 · 单入口）

三个前端（顾客点单 / 厨房看板 / 后台管理）在构建阶段一次性打包成静态文件，运行时由**一个 Nginx 容器**统一伺服，并把 `/api` 与 `/media` 反代给 Edge API。整套栈只有三个容器：

```
                    ┌─────────────────────────────┐
   浏览器  ────────► │  web (nginx :80)            │
                    │   /        → 顾客点单        │
                    │   /kds/    → 厨房看板        │
                    │   /admin/  → 后台管理        │
                    │   /api/    ─┐               │
                    │   /media/  ─┤ 反向代理       │
                    └─────────────┼───────────────┘
                                  ▼
                          ┌───────────────┐     ┌──────────────┐
                          │ api (:8080)   │───► │ postgres     │
                          │ FastAPI       │     │ (仅内网)      │
                          └───────────────┘     └──────────────┘
```

三个站同源，所以前端用相对地址 `/api/v1` 调用后端，CORS 直接留空。

## 首次部署

```bash
# 1. 准备配置
cp deploy/.env.production.example deploy/.env.production

# 2. 生成密钥并填进去
openssl rand -hex 32      # → JWT_SECRET
openssl rand -base64 24   # → POSTGRES_PASSWORD

# 3. 启动（首次会构建镜像，约几分钟）
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production up -d --build
```

数据库迁移由 api 容器在启动时自动执行（`alembic upgrade head`），不需要手动跑。

### 创建第一个门店和管理员账号

```bash
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production \
  exec api python -m app.cli bootstrap-store \
  --tenant-code ACME --tenant-name "Acme Drinks" \
  --legal-entity-code ACME-NL --legal-entity-name "Acme Drinks B.V." \
  --store-code STORE01 --store-name "Amsterdam Centraal" \
  --owner-username owner --owner-display-name "Store Owner"
```

密码会以隐藏输入方式提示，不要用 `--owner-password` 传（会留在 shell 历史里）。命令会输出 kiosk 和 厨房看板 的设备凭据，记下来——首次打开这两个前端时要填。

## 日常操作

```bash
# 查看状态和日志
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production ps
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production logs -f api

# 更新代码后重新部署
git pull
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production up -d --build

# 备份数据库
docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production \
  exec -T postgres pg_dump -U sippilot sippilot | gzip > backup-$(date +%F).sql.gz
```

命令较长，可以在 shell 里加个别名：

```bash
alias sp='docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production'
```

## HTTPS

Nginx 容器只监听 80 端口，明文。生产环境必须在前面加 TLS，两种做法：

**推荐 · 宿主机 Caddy 或 Nginx 反代**：把 `HTTP_PORT` 改成 `8080`，然后由宿主机上的 Caddy 处理证书（自动签发续期）：

```
shop.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

**或者**在 compose 里加一个 Caddy/Traefik 容器接管 80/443。

没上 TLS 之前有两个实际后果：后台登录凭据明文传输；kiosk 和看板前端的 `normalizeApiBaseUrl` 只允许非 loopback 地址走 HTTPS，所以用域名明文访问时它们会拒绝连接。

## 数据持久化

两个 named volume，`docker compose down` 不会删（要删得显式加 `-v`）：

- `postgres-data` — 数据库
- `media-data` — 后台上传的商品图片

备份时这两个都要覆盖，只备份数据库会丢图片。

## 上线前检查

- [ ] `JWT_SECRET` 已生成且不少于 32 字节（改这个值会让所有已签发的员工令牌失效）
- [ ] `POSTGRES_PASSWORD` 已改成随机值
- [ ] TLS 已配置
- [ ] `MOCK_PAYMENT_ENABLED` 保持 `false`（compose 已写死；`APP_ENV=production` 下若为 true，API 会拒绝启动）
- [ ] 后台管理是内部系统，考虑在 TLS 层给 `/admin/` 和 `/kds/` 限制来源 IP 或加一层认证——目前它们和顾客点单页一样对公网开放，只靠应用自身的登录保护

## 路径前缀说明

前端构建时通过 `--base` 注入前缀，必须和 [nginx.conf](nginx.conf) 里的 `location` 保持一致：

| 应用                | 构建参数         | 访问路径  |
| ------------------- | ---------------- | --------- |
| kiosk-web           | （默认 `/`）     | `/`       |
| kitchen-display-web | `--base=/kds/`   | `/kds/`   |
| admin-web           | `--base=/admin/` | `/admin/` |

改前缀要同时改 [web.Dockerfile](web.Dockerfile) 的构建参数和 [nginx.conf](nginx.conf) 的 location 块。
