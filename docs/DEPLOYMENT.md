# Linux 服务器部署

当前仅交付部署配置，尚未连接用户的阿里云服务器。
以下以代码 `/opt/day-enough`、数据 `/var/lib/day-enough`、服务用户 `dayenough` 为例。
需按真实发行版安装 Python 3.11+ 与 venv，HTTPS 方案需先确认域名与服务器访问条件。

## 部署前核对

先 SSH 登录服务器，运行以下只读命令，确认发行版、Python、已有网站及端口占用：

```bash
cat /etc/os-release
python3 --version
sudo ss -ltnp
sudo systemctl status nginx caddy --no-pager
```

最后一条命令显示某个服务不存在或未运行是正常情况。若服务器已有 Nginx/Caddy 或 8000 端口被占用，先确认现有配置，再选择未占用的本地端口或合并站点配置；同步调整 systemd 与反向代理的端口。若已有个人任务，先从本机应用的「设置」导出 JSON，部署成功后再导入服务器。请勿把数据库、`secret.key` 或密码提交到 Git。

以下包管理命令仅适用于 Ubuntu/Debian；其他发行版按其官方方式安装等价软件。系统提供的 Python 若低于 3.11，先安装受支持的 Python 版本，不要用旧版本继续创建虚拟环境。

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git curl
python3 --version
```

## 1. 应用环境

由管理员建立专用非 root 服务用户，准备代码目录，并让该用户可写数据目录：

```bash
sudo useradd --system --home /var/lib/day-enough --create-home --shell /usr/sbin/nologin dayenough
sudo install -d -o dayenough -g dayenough -m 700 /var/lib/day-enough
sudo install -d -o dayenough -g dayenough /opt/day-enough
```

将仓库代码放到空的 `/opt/day-enough`。以下使用本仓库当前的 GitHub HTTPS 地址；若仓库为私有，应先配置只读部署密钥并将 URL 改成 SSH 地址，不要把访问令牌写进命令或 Git URL：

```bash
sudo -u dayenough git clone https://github.com/TangBeiYang/day-enough.git /opt/day-enough
cd /opt/day-enough
```

确认仓库中已有要部署的最新提交。以应用用户安装生产依赖，并交互式设置服务器的个人密码：

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
sudo systemctl status day-enough --no-pager
curl -I http://127.0.0.1:8000/
```

服务只监听 `127.0.0.1:8000`，不能从公网直接访问。个人负载默认 1 worker、2 threads，避免为 2GB 机器部署多余服务。SQLite 本地磁盘保存，不挂载网络文件系统。

## 2. HTTPS 访问

若已有可用域名，使用 Caddy（如服务器已有 Nginx，可复用现有代理，不必再装 Caddy）。空的 Ubuntu/Debian 服务器可按 [Caddy 官方安装说明](https://caddyserver.com/docs/install) 安装稳定版：

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

空服务器可先备份 Caddy 安装后的默认配置，再复制本仓库示例并用编辑器把 `planner.example.com` 换成真实域名；已有网站则只把示例站点块合并到原配置，不要覆盖其他站点：

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-day-enough
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudoedit /etc/caddy/Caddyfile
```

- 域名 DNS 指向服务器。
- 服务器防火墙与[阿里云安全组入方向规则](https://help.aliyun.com/zh/ecs/user-guide/start-using-security-groups)允许 TCP 80/443；8000 不对公网开放。
- 通过 HTTPS 访问，服务配置保持 `DAY_ENOUGH_SECURE_COOKIE=1`。
- 个人数据目录不对外作为静态文件提供。

验证 Caddy 配置后重新加载：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy 会按域名自动管理证书，见 [反向代理官方说明](https://caddyserver.com/docs/quick-starts/reverse-proxy)。
Gunicorn 运行方式参照 [Flask 官方部署说明](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)。
确认 `https://你的域名/` 能正常打开和登录后，在另一台设备登录同一地址，检查两端读取的是同一份任务。

没有域名时，可以先使用 SSH 本地端口转发私下试用，而不是直接公网暴露 HTTP 登录页。此方式浏览器地址为本机 HTTP，需要在 service 中将 Secure cookie 环境变量设为 `0` 后重启：

```bash
ssh -N -L 8000:127.0.0.1:8000 你的SSH主机别名
```

每台电脑建立自己的隧道，再打开 http://127.0.0.1:8000 。正式 HTTPS 访问时恢复 Secure cookie 为 `1`。

## 3. 备份和迁移

完整在线备份（每次使用不同文件名）：

```bash
cd /opt/day-enough
sudo -u dayenough env DAY_ENOUGH_DATA=/var/lib/day-enough .venv/bin/flask --app day_enough backup "/var/lib/day-enough/backups/manual-$(date -u +%Y%m%dT%H%M%SZ).sqlite"
```

可安装附带的 `day-enough-backup.service` 与 `.timer` 每天运行，默认保留所有快照，不自动删除；个人数据量很小，按需手动清理。备份应定期另存到个人电脑或其他机器，仅同盘备份不能应对服务器损坏。

```bash
sudo cp deploy/day-enough-backup.service deploy/day-enough-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now day-enough-backup.timer
sudo systemctl list-timers day-enough-backup.timer
```

迁移本机任务的简单办法：先从本机应用「设置 → 导出 JSON 备份」，在服务器初始化新实例并设置密码，再登录服务器网站，在「设置 → 从备份恢复」导入。恢复会替换服务器当前任务数据；导入前先核对所选文件。无需迁移阿里云专有资源。

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

升级前先备份，再更新代码/依赖和重启。当前 schema 为 v6，启动时自动补齐阶段计划表以及此前的计划日期、周期规则与单次删除标记等结构，保留已有任务、计划和投入记录；旧规则保留原截止方式。新 JSON 备份为 v6，应用兼容恢复 v1–v5；回退旧代码时需同时恢复升级前的数据库备份。后续结构变更仍须提供显式迁移，不能只修改建表语句。
当前登录限流由 SQLite 存储，代理后的请求共同计入个人实例的 5 分钟 10 次额度；不信任任意客户端传入的代理 IP 头。
