# 隐私与脱敏

## 本仓库允许的内容

只包含通用程序、人工合成测试、部署模板、协议说明和公开参考链接。初始发布在新目录和全新 Git 历史中构建，没有迁移原始项目的 Git 历史或证据日志。

## 绝不能提交的内容

- 小米密码、验证码、Token、配对会话安全字段、Cookie、登录链接或二维码。
- 实际用户 ID、设备 ID、SID、MAC、手机号、邮箱、真实服务器地址及 SSH 配置。
- HAR/PCAP、SQLite/备份、JSONL/CSV、健康报告、轨迹、截图与未清理运行日志。
- FDS 对象名、对象密钥、带签名下载 URL、精确活动时间和位置、用户数据哈希或由真实数据生成的示例。
- 旧项目的验证报告、回滚脚本、补丁、依赖本机绝对路径的 lock 文件或打包的虚拟环境。

字段名如 `service_token`、`ssecurity`、`sid` 为协议所必需，不是秘密值；测试使用显式 `FIXTURE`、`FAKE_TOKEN`、`SYNTHETIC_ACCOUNT` 或代码生成的人工值。NIST AES 测试向量是公开算法测试数据，不是小米密钥。

## 发布前

```sh
.venv/bin/python scripts/check_publish.py
git config core.hooksPath .githooks
git add README.md SECURITY.md THIRD_PARTY.md LICENSE .gitignore .githooks \
  cloud_export_web.py poll_once.py parse_health.py fds_tools.py \
  requirements.txt requirements-fds.txt docs deploy scripts tests
.venv/bin/python scripts/check_publish.py --staged
git diff --cached --stat
git diff --cached
```

扫描器限制文件路径、拒绝数据文件与常见秘密格式；它不能识别所有个人信息或证明代码绝无安全问题。私有仓库也不是上传真实健康数据的理由。

运行数据建议放在仓库外的私有目录；本项目默认 `private/` 仅为本地使用便利，不会自行上传数据。不能对凭证或健康文件生成可公开访问的下载链接。

如果发现误传，先撤销凭证、删除暴露内容并清理历史，再评估健康数据或位置泄露；仅在新提交里删文件不代表历史已被移除。不要在 Issue 中附上敏感样本。
