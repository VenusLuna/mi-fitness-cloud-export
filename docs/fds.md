# 独立运动文件与 GPS：手动链路

**本页是协议方法和离线工具，不是已经接入定时任务的自动轨迹下载器。** 当前 `poll_once.py` 只获取运动记录摘要；FDS 地址、对象名、对象 key、原始文件和解码轨迹都必须私有保存。

## 1. 从本人运动记录取参数

使用 sports 流中一条确切、本人有权读取的运动记录，不猜测其他人的标识。读取其外层 `sid` 和二次解码 value 的 `time` / `start_time`、`timezone`、`proto_type`。其中 `timezone` 为四分之一小时单位，不能误传外层以秒表示的 `zone_offset`。

SID 是此记录参与服务器命名的标识；不要把 value 里的硬件 `did` 代替它。

可选运动扩展接口：`GET /app/v1/operate/get_sport_operational_data`。`route_info` 为空并不证明没有 GPS。`GET /app/v1/running_route/get_user_routes_list` 业务参数错误也不能当成“0 条轨迹”。这两个接口均不在主同步器白名单中，本文没有把失败探测变成定时任务。

## 2. 构造 suffix

```text
tag = (128 + (proto_type << 2) + file_type) & 255
prefix = uint32_le(timestamp) + uint8(timezone & 255) + uint8(tag)
suffix = base64url_no_padding(prefix) + "_" + base64url_no_padding(SHA1(sid))
```

观察到的文件类型为 0（运动采样）、1（报告类）、2（GPS）、3（恢复类）；不是每类都会返回可下载文件。仅类型0、2的下载与解密曾得到实测验证，其余不保证格式。

```sh
.venv/bin/python fds_tools.py suffix --record private/activity.json \
  --file-type 2 --out private/gps-request-item.json
```

活动文件必须是自己导出的单条原始 sports 对象，不是含 `raw` 包装的整行。输出 suffix 仍然敏感，不打印到共享日志。

## 3. 请求下载元数据

使用本人会话构造 SDK 加密 GET 参数：

- 网络地址：`https://hlth.io.mi.com/healthapp/service/gen_download_url`
- **签名路径：`/service/gen_download_url`**，不是完整网络路径。
- 明文请求结构：`{"did": SID, "items": [{"timestamp": TIMESTAMP, "suffix": SUFFIX}]}`。
- `SID`、`TIMESTAMP`、`SUFFIX` 是必须从本人记录绑定的参数，不是可直接发送的字面值。
- 调用 `build_encrypted_params("GET", signing_path, ssecurity, params)`；保留该请求 `_nonce`，用同一配对会话解密响应，校验 `code=0`。
- `result` 映射键可能为 `suffix + "_" + timestamp`；检查条目的 `url`、`method`、`obj_key`、过期时间。没有 key 或可用 URL 的条目不能假装下载成功。

主同步器故意不开放任意 URL/路径，也没有 FDS 网络 CLI；若实现这一段，应使用独立、最小只读白名单，而不是删除现有路径安全检查。

## 4. 下载与解密

以元数据给出的 GET 地址请求文件：只允许经验证的小米 FDS HTTPS 主机；验证 DNS 为公网、设置超时和最大大小、拒绝重定向。已有实例使用 `cnbj1.fds.api.xiaomi.com`，其他地域主机必须单独核实，不能无条件信任任意响应 URL。DNS 检查本身也不能完全防止重绑定，独立下载器还应考虑连接地址约束。

**CDN 请求不得带小米账号 Cookie、serviceToken、Authorization 或登录会话客户端的 Cookie jar。** 签名 URL 已是临时授权，不应公开。文件内容可能为 JSON 字符串或裸 base64url 文本。

解码后采用 AES-CBC，key 为条目 `obj_key` 的 base64url 解码值，IV 为协议常量 ASCII `1234567887654321`，PKCS#7 去填充。这个固定 IV 是协议常量，不是泄漏的个人凭证，也不应照搬为新系统的加密设计。

```sh
.venv/bin/python -m pip install -r requirements-fds.txt
.venv/bin/python fds_tools.py decrypt private/gps.ciphertext \
  --key-file private/object-key.json --out private/gps.bin
.venv/bin/python fds_tools.py decode-gps private/gps.bin \
  --out private/gps-points.json
```

`object-key.json` 是权限600、仅本地存在的对象 key 文件，字段名为 `obj_key`；不要在命令行写密钥。工具只离线解密，不下载、不发送数据。

## 5. GPS 格式与校验

- 9字节头：时间戳 uint32_le；时区四分之一小时；GPS版本；协议类型；保留字节；字段有效位。
- 版本1有时间戳、经度float32、纬度float32。
- 版本2增加精度float32和打包速度uint16，记录长18字节；GPS来源和速度共用打包值。
- 版本3增加海拔float32和HDOP float32；版本4另外包含uint32记录数量。当前工具支持版本1—4，其他版本直接拒绝。
- 校验记录长、数量、有效位、浮点值和坐标范围；保留顺序与重复时间戳，不平滑、不补点、不调用第三方地图。
- 额外校验文件头时间和 proto_type 与本人运动记录匹配、点位时间在运动窗口内、缺失起始时段与最大间隔；**离线工具返回解码结果，不自动证明完整轨迹。**

原始坐标系未经确认时，不能宣称为WGS84或GCJ-02，也不能直接认为地图偏移就是定位错误。当前工具输出带未确认标记的JSON；GPX/GeoJSON转换需要另行保留这一限制，不随意补造缺失坐标。

运动采样类型0虽然可解密，其内部业务格式依赖版本与协议类型，本仓库不宣称已实现所有逐秒采样字段解码。
