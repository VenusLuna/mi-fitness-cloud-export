# 登录与云端读取协议

## 数据链路与前提

手环/体脂秤 → 手机 App 或支持的蓝牙网关 → 小米云端 → 本人登录会话 → 只读接口 → 私有 SQLite/JSONL/CSV。

本项目调用的是 `hlth.io.mi.com`，不是米家设备控制接口。体脂秤可能绑定米家，**但绑定米家不等于本项目的健康云端一定存在体成分数据**；需要按实际账号和 App 同步结果验证。这里不包含 BLE 配对、米家登录、网关固件或向 Apple Health 写入的实现。

## 会话获取

`mi-fitness==0.2.0` 提供小米官方登录流程。包装器关闭上游调试日志，检查认证请求为 HTTPS 且目的域名属于小米，将会话字段原子写入本地 `600` 文件。密码、验证码不由脚本收集或写入代码。

需要成对保存的字段名称包括 `user_id`、`c_user_id`、`service_token`、`ssecurity`；自动续期还可能依赖 `pass_token`。这里只列字段名，仓库不提供任何实际值。不存在通用共享 Token，也不能从不含 `ssecurity` 的 HAR 凭空恢复配对会话。

`--web` 只是把一次性官方登录 URL 写到私有文件供本机浏览器打开，不是抓取浏览器 Cookie。授权失败、验证码或风控需要本人在官方界面处理。

## 加密

业务接口由 SDK 的 `build_encrypted_params()` 和 `decrypt_response()` 完成签名与 RC4 业务层编解码，包括 nonce、派生密钥、`rc4_hash__`、`signature`。TLS 与业务加密是两层，不可用“HTTP 200”代替业务码和解密结构校验。

程序只将健康 Cookie 发送到固定的 `https://hlth.io.mi.com`，不跟随业务请求重定向，不使用环境代理配置；若需要代理，应自行审查安全边界，不能关闭证书验证解决连接问题。

## 已使用的只读接口

| 流 | POST 路径 | 结果列表 |
|---|---|---|
| fitness | `/app/v1/data/get_fitness_data_by_watermark` | `result.data_list` |
| aggregated | `/app/v1/data/get_aggregated_fitness_data_by_watermark` | `result.data_list` |
| sports | `/app/v1/data/get_sport_records_by_watermark` | `result.sport_records` |
| project | `/app/v1/data/get_project_data_by_watermark` | `result.data_list` |

参数以当前 `waterMark` 为起点；aggregated 额外传 `tag=daily_fitness`。`get_max_watermark` 在白名单中，但不是全历史覆盖证明。

近期补查为 `/app/v1/data/get_fitness_data_by_time`，当前查询键为 heart_rate、sleep、steps、spo2、stress、calories；体重通过 fitness 水位流获得。该接口的 `startTime`/`endTime` 采用毫秒请求值，但返回记录中的 `time` 常为秒，两者不能混用。

## 游标与失败处理

- 校验 HTTP 状态、业务 `code=0`、列表结构、`has_more` 和非负整数水位。
- 初始空列表伴随前进水位可能是种子页，需要继续，不直接结束。
- 尾页返回水位 0 不倒退已有游标；停滞、回退、未知结构保存原页并明确报错。
- 达到页数上限保留游标，下一轮续传；成功页尾仍标记 `server_reported_end_not_full_history`。
- `history_pending=false` 不是所有历史或其他数据通道完整的证明。
- 数据库存原始响应、传输记录与版本，全部按敏感数据保护，不应分享其哈希明细作为“脱敏数据”。

项目不调用删除、上传、亲友邀请或其他账号管理业务接口。
