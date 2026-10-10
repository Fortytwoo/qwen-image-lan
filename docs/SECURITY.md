# 数据、Passkey 与恢复

## 认证和存储

密码接口返回 410。首次设置由服务电脑的 Windows 用户生成一次性注册授权，后续由已登录设备生成授权或添加 Passkey；没有公开自助注册。

WebAuthn 验证 challenge、Origin、RP ID、签名、用户标识、UP/UV 标记及签名计数器。可发现凭据和设备验证均为 required。挑战保留 3 分钟、绑定安全 Cookie 与客户端地址、只使用一次。会话 Cookie 为 Secure、HttpOnly、SameSite=Strict，8 小时有效，服务重启后需重新登录。撤销 Passkey 会使相应会话失效。

HTTPS 网关只绑定指定私有 IPv4，另校验来源网段和 Host；不信任代理转发的客户端地址。所有写操作验证 Origin，已登录业务操作还验证 CSRF。引擎只绑定 loopback。

`service/private/` 保存：

- `keys.dpapi`：数据加密密钥、会话密钥、TLS 私钥保护口令；没有网站密码。
- `passkeys.dpapi`：公钥、签名计数、设备名称和一次性授权记录；没有 Passkey 私钥。
- `*.encrypted.pem`：加密的 TLS/CA 私钥。
- `archive/*.meta.enc`、`*.reference.enc`、`*.image.enc`：AES-256-GCM 元数据、上传原文件和生成结果。

每份密文使用随机 nonce 和记录/用途绑定的 AAD。不同用途密文不能互换。原图提交给模型前持久化，结果在返回完成状态前加密保存，浏览器关闭后后台仍跟踪任务。

DPAPI 与 NTFS ACL 绑定当前 Windows 用户，服务也以该用户运行。这主要保护磁盘数据和未授权的 LAN 访客；不能防止已控制该 Windows 用户、管理员或运行中进程内存的攻击者。模型运算和浏览器查看时内容必然在内存中解密。

## 备份与设备恢复

备份安装目录的配置、证书、`private/` 和原 Windows 用户恢复环境；不要把这些内容提交 GitHub。只复制密文到另一 Windows 用户或重装后的系统，通常无法解开 DPAPI。迁移应在原用户环境仍可用时明确安排密钥恢复，而不是直接重建数据密钥。

服务端没有设备 Passkey 私钥。Passkey 丢失时，由服务电脑原 Windows 用户运行 `Register-Qwen-Passkey.cmd`，添加新的 Passkey；至少保留一把有效凭据，再撤销旧设备。

下载到浏览器的 PNG/JPEG/WebP 或 JSON 是普通文件；服务端保留的副本仍加密。历史默认长期保留，文件增长由使用者自行管理。没有公开删除 API。

## 发布约定

仓库只能包含源码、文档、固定下载清单、上游公开 UI 和测试。不得包含运行配置、密钥、证书、Passkey、注册令牌、日志、模型或用户产出。

发布前运行 `scripts/check_public_tree.py`，检查暂存文件及 Git 历史。报告问题时只提供经过脱敏的错误摘要，不上传 `private/` 或认证验证正文。
