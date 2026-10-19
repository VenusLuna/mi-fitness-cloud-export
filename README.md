# 小米手环与体脂秤：本人账号云端数据导出

非官方、只读、可续传的小米运动健康数据获取方法。整理的是**方法与通用代码**，不包含任何真实账号、健康记录、HAR、设备标识、轨迹、服务器地址或登录凭证。

面向小米手环及小米体脂秤（例如 S400）数据归档。两类设备最终都可以表现为健康记录，但是否进入本文使用的云端取决于设备、地区、App 和绑定方式；不把“设备支持云同步”当作此接口一定可读的证明。

## 能做什么

| 数据 | 路径 | 边界 |
|---|---|---|
| 心率、睡眠、步数、血氧、压力等 | `fitness` 水位流 | 设备已上传到本人小米运动健康云端的数据 |
| 体重、体脂、肌肉、水分等 | `fitness` 中的 `key=weight` | 必须已经进入同一账号的小米运动健康；不同设备、地区和绑定方式不保证支持 |
| 每日活动摘要 | `aggregated` 水位流 | `tag=daily_fitness`，不能把活动消耗与基础代谢混为一谈 |
| 运动类型、时间、距离、运动心率等 | `sports` 水位流 | 是运动记录，不是力量训练动作识别器 |
| 项目数据 | `project` 水位流 | 实际返回可能为空，不等于运动种类列表 |
| GPS、独立运动文件 | 独立 FDS 下载链路 | 不在十分钟任务中；见 [轨迹方法](docs/fds.md) |

**不承诺全历史完整，不读取 Apple Health，也不能强制手环或手机上传。** 云端业务码成功、定时任务成功、权限已打开，都不是“所有数据已导出”的证据。

## 快速使用

Python 3.11+；定时脚本使用 POSIX 文件锁，推荐 Linux。依赖通过 PyPI 安装，不分发第三方 SDK 源码或 wheel。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -m 700 private
.venv/bin/python cloud_export_web.py status
.venv/bin/python cloud_export_web.py login --web
```

登录时程序只输出 `private/web-login.private.json` 的位置。**在本机私下读取其中的登录链接并打开小米官方网页，完成本人登录**；不要将链接、二维码、短信验证码、密码或 JSON 内容发到聊天、Issue 或日志。不要把仍在登录的 URL 提交到 Git。

完成后，`private/token.json` 应为 `600` 权限。普通账号管理页“已登录”不等于导出工具已经取得配对的 `service_token` 与 `ssecurity`。

```sh
.venv/bin/python cloud_export_web.py sync \
  --streams fitness,aggregated,sports,project --max-pages 40

.venv/bin/python parse_health.py private/health.sqlite \
  --sqlite --out private/parsed-first-run
```

输出目录必须是新的；重复解析请换一个目录。首次历史回填可能需要多轮，页数上限表示本轮未完成，游标会保留；不可把它改写成“全量成功”。

## 每十分钟增量拉取

```sh
.venv/bin/python poll_once.py --state private --history-pages 40
```

该命令使用已有凭证，同步四个水位流，额外查询六类近期首屏数据，并将新内容导出 JSONL/CSV。**近期接口的查询时间范围与 `limit` 未证明得到服务端严格执行，不能据此保证七天完整覆盖。** 每轮有页数、时间和磁盘余量限制。

Linux systemd 配置见 [部署文档](docs/deploy.md)。它是模板，不会修改任何已有服务器。

## 体脂秤字段

`key=weight` 的 `value` 可能是 JSON 字符串，需要二次解析。观察到的字段包括：

`weight`、`bmi`、`body_fat_rate`、`fat_mass`、`fat_free_body`、`muscle_mass`、`skeletal_muscle_mass`、`body_moisture_mass`、`moisture_rate`、`protein_mass`、`protein_rate`、`bone_mass`、`visceral_fat`、`basal_metabolism`、`bpm` 等。

字段是否出现取决于设备、账号绑定与云端实际数据；**不保证每次都有全部指标，也不能仅凭这些字段认定设备型号。** 秤上单次 `bpm` 不能代替手环的日静息心率。体成分为设备估算，不能用身体年龄字段猜测真实年龄。

## 文档

- [登录、加密与接口](docs/protocol.md)
- [手环与体脂秤分别怎么取数据](docs/devices.md)
- [解析、删除标记和重复版本](docs/data-model.md)
- [FDS/GPS 手动下载与离线解码](docs/fds.md)
- [Linux 定时部署](docs/deploy.md)
- [脱敏和发布边界](SECURITY.md)
- [依赖与参考来源](THIRD_PARTY.md)

## 测试与发布检查

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_publish.py
git config core.hooksPath .githooks
```

所有测试数据均为人工构造；测试不访问账号或云端。FDS AES 测试需要安装 `requirements-fds.txt`。合成测试通过不等于任意账号、地区或固件都能运行。

`.gitignore` 和扫描器是辅助防线，不是敏感数据识别的绝对保证；每次提交仍需审阅 `git diff --cached`。运行目录与数据备份必须留在私有位置。
