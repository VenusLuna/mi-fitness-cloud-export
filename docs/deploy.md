# Linux：每十分钟拉取

这里是通用模板，**不包含实际服务器、IP、账号凭证或运行数据**。以下步骤会在你选定的新主机上创建专用用户和目录；部署前审查命令，不要覆盖已有安装。

## 安装

将代码放入 `/opt/mi-fitness`，在其中创建虚拟环境、安装 `requirements.txt`。创建无交互登录的服务用户，并建立仅其可读写的状态目录：

```sh
sudo useradd --system --home-dir /var/lib/mi-fitness --shell /usr/sbin/nologin mifitness
sudo install -d -m 700 -o mifitness -g mifitness /var/lib/mi-fitness
```

先在可信本机完成登录。使用经过主机密钥核验的 SSH/SFTP，把私有 token 文件传到服务的状态目录，设置属主为 `mifitness`、权限 `600`。**不要把 Token 放到 GitHub Secrets、Git 仓库、网页根目录或命令行参数。** 也可在服务器上以专用用户完成同一登录流程。

代码和虚拟环境由管理员管理，服务用户只读；不要递归 chmod 虚拟环境中的符号链接。服务运行前确保状态目录所在分区有至少 4 GiB 可用空间。

## 首次执行与启用

审阅 `deploy/mi-fitness-sync.service` 和 `.timer`，确认路径、时区、用户和权限后：

```sh
sudo install -m 644 deploy/mi-fitness-sync.service /etc/systemd/system/
sudo install -m 644 deploy/mi-fitness-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start mi-fitness-sync.service
sudo systemctl show mi-fitness-sync.service -p Result -p ExecMainStatus
sudo systemctl enable --now mi-fitness-sync.timer
sudo systemctl list-timers mi-fitness-sync.timer
```

时间设置为 Asia/Shanghai 每十分钟。`Persistent=true` 会在恢复后补触发错过的日历任务，并不补造缺失的健康数据。`Type=oneshot` 执行完成后 inactive/dead 是正常现象，应同时看 Result、状态文件和数据时间。

## 验证与停止

私下查看状态目录中的 `status.json`、增量导出 manifest、最新记录时间和错误字段，区分“运行成功”“新增 0 条”“手机未上传”“全历史未核实”。原始日志也可能包含敏感信息，不应贴到 Issue。

```sh
sudo systemctl disable --now mi-fitness-sync.timer
```

停止定时器不会删除数据库或撤销小米登录。卸载前妥善保存私有数据，若凭证泄露应在官方账号处撤销/重新登录，不以删除 Git 最新文件代替凭证轮换。

**当前定时任务不下载 FDS/GPS。** 将来接入需要另行处理签名 URL 过期、密钥保管、下载白名单、数据量及运动记录更新；不能把本文模板当作已实现该功能。
