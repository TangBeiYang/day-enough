# DayEnough

A personal task planner that helps you decide what to work on today—and how much is enough—based on deadlines, available time, and energy.

个人使用、电脑优先的任务规划工具。不同电脑和系统通过浏览器访问同一份服务端数据。

## 当前功能

- 个人密码登录，无注册和第三方账号。
- 任务录入、编辑、归档和恢复推进；记录剩余估计与实际投入。
- 根据截止日期、后果严重度、剩余用时及今日状态生成计划。
- 今日份额、部分进展、跳过、手动排序、主动重排。
- 今日计划持久保存，完成后不会自动添加任务。
- 跨设备版本冲突保护、重复操作保护、上海时区跨天检查。
- JSON 导出/恢复、在线 SQLite 备份、默认时间与密码设置。

技术：Python 3.11+、Flask、SQLite、原生 HTML/CSS/JavaScript。无需 Node 构建、外部字体、AI API 或 CDN。生产环境使用 Linux + Gunicorn。

## 本地运行

在项目根目录执行（Linux/macOS；Windows 可使用 WSL）：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/flask --app day_enough set-password
.venv/bin/flask --app day_enough run --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。首次命令会交互式设置个人密码（至少 12 个字符），不需要写入源代码。未设置密码时，应用会停留在初始化提示。

忘记密码可重新执行 `set-password`，原有登录会话失效，任务不变。

开发服务器仅用于本机试用；服务器部署见 [部署说明](docs/DEPLOYMENT.md)。

## 每天怎么用

1. 添加任务，估计还需要多少分钟。长期项目可以分多天推进，可写一个具体下一步。
2. 在「今天」设置可支配分钟与精力，生成计划。
3. 做完一部分用「记一部分」；完成推荐份额用「完成今日份额」。
4. 如果实际难度不同，在「任务」中修正剩余估计。
5. 当前份额全部处理后，可以收工。新增任务或调整状态不会自动增加安排，需主动重排。

截止日期按上海时区当天结束处理。精力为粗略的高消耗任务限额，不是医学或生理量表。
重排会扣除当天已记录投入，并保留已完成、已跳过份额。跳过只影响当天。
未来可用时间暂按每日默认时间估计（包括周末），未来精力按「一般」估计；截止风险提示是估计，不是按时完成保证。

## 数据与备份

默认数据目录是项目下的 `instance/`，包含 SQLite 数据库与会话签名密钥，已加入 `.gitignore`。
可用环境变量 `DAY_ENOUGH_DATA` 指定其他绝对路径。

- 日常备份：设置 → 导出 JSON（只含任务/计划/投入/默认时间，不含密码）。
- 恢复：设置 → 从备份恢复，输入「恢复」。**会替换所有任务数据**，先导出当前数据。
- 服务器完整备份：

```bash
.venv/bin/flask --app day_enough backup backups/day-enough-2026-09-14.sqlite
```

备份命令使用 SQLite backup API，允许在服务运行时执行，拒绝覆盖已有文件并校验完整性。不要直接复制运行中的 SQLite 主文件，因为可能还有未合并的 WAL 数据。
完整备份包含密码哈希，应与个人数据一起妥善保存；迁移流程见部署说明。

## 验证

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check day_enough/static/app.js
```

浏览器验收（可选，使用临时数据库，不修改个人数据）：

```bash
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/python tests/browser_smoke.py
```

默认使用 `/usr/bin/google-chrome`；其他位置可通过 `CHROME_BIN` 指定。
截图输出在忽略的 `test-results/`。Node 仅用于可选的 JS 语法检查，应用本身不依赖 Node。

## 开发接续

新会话先读 [工作状态](docs/WORK_STATUS.md) 和 [MVP 范围](docs/MVP.md)。
每完成一个可验证的小阶段，更新状态文件，记录下一步和检查结果。

## 暂未实现

周期任务、问卷、自适应学习、周视图、AI、推送通知、离线同步、多用户。
数据有变动时使用「刷新」读取；当前不做后台实时推送。尚未连接或部署到阿里云服务器。
