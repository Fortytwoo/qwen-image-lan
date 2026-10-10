# Qwen Image LAN

把 **Qwen-Image-2.1-Turbo GGUF** 部署成中文局域网生图与改图服务：HTTPS、Passkey 登录，原图、提示词、参数和结果在本机加密留存。

> 服务端目前支持 Windows x64 + NVIDIA CUDA。macOS、手机等设备可作为浏览器客户端。模型权重和引擎二进制通过固定版本清单下载，不存入 GitHub。

## 交给 Agent 安装

复制下面的提示词给能运行本机命令的 Agent（Codex、Claude Code 等）。完整版本在 [Agent 安装引导](docs/AGENT_INSTALL_PROMPT.md)。

```text
请在我的电脑安装 https://github.com/Fortytwoo/qwen-image-lan 。
先阅读 README.md、AGENTS.md 和 docs/AGENT_INSTALL_PROMPT.md，然后检查 Windows x64、NVIDIA 显卡/显存、内存、可用磁盘、局域网 IPv4、主机名及端口。
使用仓库的 Install-Qwen.ps1 安装到独立目录，用 uv 创建环境，按 models-manifest.json 的固定版本、大小和 SHA256 校验下载；保留已有 ComfyUI、模型、未提交改动和其他服务。
只开放局域网 HTTPS，采用 Passkey，不建立密码登录或公网穿透。生成本机独立 CA 和 DPAPI 密钥，保留原图、提示词、参数及结果的加密历史。
常规、安全、可逆的操作直接完成。证书信任和真实 Passkey 创建提示由我本人确认，不能模拟我的凭据或索取 PIN/密码。
验证安装、启动、健康检查、Passkey 登录和中文生图/改图，分别说明自动检查与本人确认的结果，最后给出入口、启动/停止方式及恢复方法。
```

## 功能

- 中文文生图与单张参考图改图，Turbo 官方 8 步、Euler、CFG 1、专用 sigmas。
- 原图预览、结果下载、历史记录、以已有结果继续改图。
- Passkey 注册与登录，支持 Windows Hello、手机或安全密钥；没有密码回退入口。
- HTTPS 传输；原图、提示词、参数和结果采用 AES-256-GCM 存储。
- 私钥和数据密钥由 Windows DPAPI 保护，私有目录限制为当前用户和 SYSTEM。
- 后台独立归档，关闭网页后仍保留已提交任务结果；已完成记录支持重启读取。
- 一次性注册链接、设备命名与 Passkey 撤销。

## 安装条件

| 项目 | 当前支持/建议 |
| --- | --- |
| 服务端 | Windows 11/Windows x64，PowerShell 5.1 或 7 |
| 显卡 | NVIDIA，约 12 GB 或更多显存，兼容 CUDA 12 的驱动 |
| 内存 | 建议 32 GB 以上；实际测试机器为 64 GB |
| 磁盘 | 本机 NTFS，至少 30 GB 可用空间，历史图片另占空间 |
| 工具 | Git（或下载仓库 ZIP）、[uv](https://docs.astral.sh/uv/getting-started/installation/) |
| 浏览器 | 支持 WebAuthn/Passkey 的新版 Chrome、Edge 或 Safari |

全部模型约 11.32 GB；引擎和 CUDA 下载包约 0.90 GB。下载脚本支持续传、逐文件校验和串行下载。此预设未验收 AMD、Intel GPU、Linux 或 macOS 服务端。

## 手工安装

在 PowerShell 中执行。先把示例地址替换成自己的 LAN IPv4、网段和主机名。

```powershell
git clone https://github.com/Fortytwoo/qwen-image-lan.git
cd qwen-image-lan
# 没有 uv 时先安装，再重新打开 PowerShell：
# winget install --id astral-sh.uv --exact
.\scripts\Install-Qwen.ps1 -HostAddress 192.168.50.10 -Network 192.168.50.0/24 -RpId my-pc.local
```

默认安装目录为 `%LOCALAPPDATA%\QwenImageLAN`，可以用 `-InstallDir 'D:\AI\Qwen Image'` 自定义。`-Port`、`-EnginePort`、`-MaxVram`、`-Threads` 可调整。安装器检测到不同的既有配置时会停止，保留原密钥、Passkey 与历史，不会自动迁移 RP ID。

安装完成后，在**安装目录**执行：

1. `Trust-Certificate.cmd`：核对本次 CA，并亲自完成 Windows 信任提示。
2. `Start-Qwen.cmd`：启动引擎和 HTTPS 服务。
3. `Register-Qwen-Passkey.cmd`：创建第一次注册链接，亲自完成设备提示。
4. 注册后退出，再通过 Passkey 登录一次。

此后的入口是 `https://你的主机名.local:8443/`；`/edit` 用于改图，`/history` 查看历史，`/passkeys` 管理通行密钥。`Stop-Qwen.cmd` 停止该安装记录的进程。

`-ConfigureOnly` 只创建配置、证书和页面，不下载权重或启动引擎，适合先检查环境。`-SkipDownloads` 仅使用已经存在并能通过大小及 SHA256 校验的文件，不代表跳过校验。

更多说明：[安装与客户端访问](docs/INSTALL.md)、[数据、认证和恢复](docs/SECURITY.md)。

## 改图范围

单张 PNG、JPEG、WebP 静态原图，不超过 8 MB、1600 万像素。原文件完整加密保存；模型参考图最长边缩至 1024，并补边到 32 的倍数。输出宽高为 256–1024 的 32 的倍数，每次一张。当前不提供蒙版局部修补或多参考图。

这是参考图条件下的重新生成。主体姿态和构图可能保留，纹理、光照及细节也可能变化。提示词应同时说明需要修改和需要保留的内容。

## 验证记录

原始部署在 RTX 5070 Ti Laptop 12 GB、64 GB 内存上实际完成：

- 1024×1024 文生图约 27–29 秒；1024×1024 改图约 51 秒（单次结果，非性能保证）。
- 中文网页上传、512×512 改图、历史继续改图、桌面和手机布局。
- 本人真实 Passkey 注册、退出后重新登录；局域网另一台设备的 HTTPS 访问。
- 原图、结果解密后逐字节一致；6 条历史在认证迁移前后未变化。

公共版本的安装器、可配置路径/地址、证书重复安装保护及安全检查另由仓库测试验证。自动虚拟认证器测试不等于替使用者完成真实设备注册。

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r service\requirements.txt
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\check_public_tree.py
```

## 来源与许可

原始 Hugging Face `Uncensored-GGUF` 仓库提供文本编码器和视觉模块，完整部署还需要配套图像模型与 VAE。固定来源见 [models-manifest.json](models-manifest.json)。

本项目代码采用 MIT。上游 WebUI、模型、CUDA 和其他依赖分别遵循自身许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。仓库不包含任何运行实例的证书、密钥、Passkey、提示词或产出。
