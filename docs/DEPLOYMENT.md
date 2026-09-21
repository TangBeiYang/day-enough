# Linux 服务器部署

当前仅交付部署配置，尚未连接用户的阿里云服务器。
以下以代码 `/opt/day-enough`、数据 `/var/lib/day-enough`、服务用户 `dayenough` 为例。
需按真实发行版安装 Python 3.11+ 与 venv，HTTPS 方案需先确认域名与服务器访问条件。

## 1. 应用环境

由管理员建立专用非 root 服务用户，准备代码目录，并让该用户可写数据目录：

```bash
sudo useradd --system --home /var/lib/day-enough --create-home --shell /usr/sbin/nologin dayenough
sudo install -d -o dayenough -g dayenough -m 700 /var/lib/day-enough
sudo install -d -o dayenough -g dayenough /opt/day-enough
```

把仓库代码放到 `/opt/day-enough`，以应用用户安装依赖。下列命令在该目录执行：

```bash
sudo -u dayenough python3 -m venv .venv
sudo -u dayenough .venv/bin/pip install -r requirements.lock
sudo -u dayenough env DAY_ENOUGH_DATA=/var/lib/day-enough .venv/bin/flask --app day_enough set-password
```

使用 `deploy/day-enough.service`，按实际路径修改后安装：

```bash
sudo cp deploy/day-enough.service /etc/systemd/system/day-enough.service
sudo systemctl daemon-reload
sudo systemctl enable --now day-enough
sudo systemctl status day-enough
```

服务只监听 `127.0.0.1:8000`，不能从公网直接访问。个人负载默认 1 worker、2 threads，避免为 2GB 机器部署多余服务。SQLite 本地磁盘保存，不挂载网络文件系统。

## 2. HTTPS 访问

若已有可用域名，使用 Caddy（如服务器已有 Nginx，可复用现有代理，不必再装 Caddy）。
按 [Caddy 官方安装说明](https://caddyserver.com/docs/install) 安装；将 `deploy/Caddyfile` 的示例域名改为真实域名，合并到现有配置，勿覆盖其他站点配置。

- 域名 DNS 指向服务器。
- 服务器与安全组允许 HTTPS 和证书验证所需的 80/443 端口。
- 通过 HTTPS 访问，服务配置保持 `DAY_ENOUGH_SECURE_COOKIE=1`。
- 个人数据目录不对外作为静态文件提供。

验证 Caddy 配置后重新加载：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy 会按域名自动管理证书，见 [反向代理官方说明](https://caddyserver.com/docs/quick-starts/reverse-proxy)。
Gunicorn 运行方式参照 [Flask 官方部署说明](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)。

没有域名时，可以先使用 SSH 本地端口转发私下试用，而不是直接公网暴露 HTTP 登录页。此方式浏览器地址为本机 HTTP，需要在 service 中将 Secure cookie 环境变量设为 `0` 后重启：

```bash
ssh -N -L 8000:127.0.0.1:8000 你的SSH主机别名
```

每台电脑建立自己的隧道，再打开 http://127.0.0.1:8000 。正式 HTTPS 访问时恢复 Secure cookie 为 `1`。

## 3. 备份和迁移

完整在线备份（每次使用不同文件名）：

```bash
cd /opt/day-enough
sudo -u dayenough env DAY_ENOUGH_DATA=/var/lib/day-enough .venv/bin/flask --app day_enough backup /var/lib/day-enough/backups/manual-2026-09-14.sqlite
```

可安装附带的 `day-enough-backup.service` 与 `.timer` 每天运行，默认保留所有快照，不自动删除；个人数据量很小，按需手动清理。备份应定期另存到个人电脑或其他机器，仅同盘备份不能应对服务器损坏。

迁移到新服务器的简单办法：先初始化新实例、设置密码，再用页面导入 JSON。无需迁移阿里云专有资源。

使用完整 SQLite 备份恢复：

1. 停止目标应用服务，并确认没有其他进程打开数据库。
2. 将目标现有数据目录整体改名保留（包含主库、WAL/SHM 和 secret.key），不要直接覆盖在线库。
3. 新建同路径数据目录，将完整备份复制为 `day-enough.sqlite`，恢复服务用户归属与权限（目录 700、数据库 600）。
4. 启动服务，生成新的 secret.key，所有设备重新登录；数据库中的个人密码保持不变。
5. 检查任务数量、最近进度、今日计划；出现问题时停止服务并恢复原数据目录。

## 4. 维护

```bash
sudo journalctl -u day-enough -n 100 --no-pager
sudo systemctl restart day-enough
```

升级前先备份，再更新代码/依赖和重启。当前 schema 为 v3，启动时自动补齐计划日期、周期关联字段、规则表、去重索引及规则截止字段，保留已有任务、计划和投入记录；旧规则保留原截止方式。新 JSON 备份为 v3，应用兼容恢复 v1/v2；回退旧代码时需同时恢复升级前的数据库备份。后续结构变更仍须提供显式迁移，不能只修改建表语句。
当前登录限流由 SQLite 存储，代理后的请求共同计入个人实例的 5 分钟 10 次额度；不信任任意客户端传入的代理 IP 头。
