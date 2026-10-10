# Agent 工作约定

- 默认中文交流，命令和错误保留英文。保留未提交改动，增量修改。
- 安装前阅读 README 与 `docs/AGENT_INSTALL_PROMPT.md`；代码修改前读 `docs/SECURITY.md`。
- 不把作者运行实例的配置、密钥、CA、Passkey、提示词、产出或日志复制到此仓库。
- 不改变 LAN-only、loopback 后端、Passkey-only、DPAPI 和 AES-GCM 的默认边界。
- 不自动迁移 RP ID，不覆盖原私有目录或重建数据密钥；配置不符时拒绝安装并说明差异。
- 使用 uv 和 Python 3.12；Windows 设置 UTF-8 环境变量；PowerShell 文本读写明确 UTF8。
- 下载遵循固定 manifest、大小、SHA256、串行请求和 5–10 秒间隔；不要执行未通过校验的二进制。
- Windows 证书信任、Passkey 新凭据及设备身份确认由本人完成。虚拟认证器只用在隔离测试实例，不能注册到正式服务。
- 修改后执行 `python -m unittest discover -s tests -v`、公开文件扫描及适用的 PowerShell/浏览器检查。
- 提交前检查 `git status`、暂存文件、secret scan 和实际运行边界；未经明确请求不 push 或发布。
