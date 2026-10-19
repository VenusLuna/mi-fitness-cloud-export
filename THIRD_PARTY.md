# 依赖与参考

- [MistEO/MiSDK](https://github.com/MistEO/MiSDK)：本项目通过 PyPI 安装 `mi-fitness==0.2.0`，使用其登录与业务加密模块。**不复制其源码或分发 wheel**；包元数据没有明确许可证字段，使用者应单独审查上游许可。PyPI wheel 的公开 SHA-256 为 `4cc7d2a2a3c91f76665848fbe8afdfef54f2e0ac54102f9eb8cd31d7873ae3b1`，见 [版本文件](https://pypi.org/project/mi-fitness/0.2.0/#files)。
- [kevinkwee/Mi-Fitness-Sync](https://github.com/kevinkwee/Mi-Fitness-Sync)：FDS 文件格式与命名算法的公开实现参考，研究对应 commit `b51fd421fbdda18b53c13aad12b6868731684583`。这里整理协议方法，并独立实现小范围离线工具，不打包上游工程。
- [Aaron-gx/mihealth-api](https://github.com/Aaron-gx/mihealth-api)：运动扩展接口参考，研究对应 commit `05edd1308025795e124f8958b20f8408c41b1c82`。文档示例与实际服务端参数可能存在差异，以本人账号的业务响应为准。
- [小米端侧数据开放定义](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2331)：帮助理解字段含义；不把端侧 SDK 和本文云端格式的单位、枚举无条件等同。
- [NIST SP 800-38A](https://csrc.nist.gov/pubs/sp/800/38/a/final)：AES-CBC 已知答案测试向量。
- `httpx`、`qrcode`、可选 `cryptography` 由各自项目许可证约束，均不在本仓库内分发。

本仓库的 LICENSE 只覆盖原创包装、文档和测试，不替第三方依赖重新授权。
