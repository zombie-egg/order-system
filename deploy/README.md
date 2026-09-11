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

# 3. 生成 TLS 证书（不带参数则自动探测公网 IP）
./deploy/make-cert.sh

# 4. 启动（首次会构建镜像，约几分钟）
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

> `nginx.conf` 和三个前端都是在**构建时**打进镜像的，所以改了它们之后必须带 `--build`。只跑 `up -d` 会沿用旧镜像，配置改动不生效。

命令较长，可以在 shell 里加个别名：

```bash
alias sp='docker compose -f deploy/compose.prod.yaml --env-file deploy/.env.production'
```

## HTTPS

Nginx 在 443 上提供 TLS，80 端口只做跳转（`/healthz` 除外，容器健康检查要用）。

**必须走 HTTPS**，不是可选项：kiosk 和厨房看板前端的 `normalizeApiBaseUrl` 拒绝「非 loopback 且非 HTTPS」的 API 地址，所以明文访问时这两个页面连不上后端。

### 当前：自签证书

```bash
./deploy/make-cert.sh              # 自动探测公网 IP
./deploy/make-cert.sh shop.example # 或指定主机名
```

证书写到 `deploy/tls/`（已在 .gitignore 中，不会提交），由 web 容器只读挂载。有效期 825 天。

浏览器会显示「不安全」警告，需要手动点「继续访问」——自签证书的固有表现，不是配置错误。首次在 kiosk 和看板设备上打开时，都要各自确认一次，否则前端的 `fetch` 会静默失败。

### 有域名后：换成 CA 签发证书

推荐宿主机装 Caddy，自动签发和续期：把 `HTTPS_PORT` 改成 `8443`，然后

```
shop.example.com {
    reverse_proxy https://127.0.0.1:8443 {
        transport http { tls_insecure_skip_verify }
    }
}
```

或者直接把 CA 签发的 `server.crt` / `server.key` 覆盖到 `deploy/tls/`，然后 `docker compose restart web`。

## 数据持久化

两个 named volume，`docker compose down` 不会删（要删得显式加 `-v`）：

- `postgres-data` — 数据库
- `media-data` — 后台上传的商品图片

备份时这两个都要覆盖，只备份数据库会丢图片。

## 上线前检查

- [ ] `JWT_SECRET` 已生成且不少于 32 字节（改这个值会让所有已签发的员工令牌失效）
- [ ] `POSTGRES_PASSWORD` 已改成随机值
- [ ] TLS 已配置（自签证书够用，但每台设备首次访问要手动信任）
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
