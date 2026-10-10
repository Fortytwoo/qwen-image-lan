import json
from pathlib import Path

config = json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8'))
print('入口：'+config['origin']+'/')
print('改图：'+config['origin']+'/edit')
print('登录方式：Passkey。密码登录已移除。')
print('首次注册或设备恢复：在本机运行 Register-Qwen-Passkey.cmd。')
