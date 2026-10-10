import argparse
import json
from pathlib import Path
import webbrowser

from passkeys import Passkeys

parser=argparse.ArgumentParser()
parser.add_argument('--config',default=str(Path(__file__).with_name('config.json')))
parser.add_argument('--open',action='store_true')
parser.add_argument('--json',action='store_true')
args=parser.parse_args()
config=json.loads(Path(args.config).read_text(encoding='utf-8'))
store=Passkeys(config['passkeys'],config['rp_id'],config['origin'])
token,expires=store.create_grant(local_owner=True)
url=config['origin']+'/register#enroll='+token
if args.open:
    webbrowser.open(url,new=2)
    print('已打开 Passkey 注册页面。请本人确认设备提示；注册链接 10 分钟内有效，只能使用一次。')
elif args.json:
    print(json.dumps({'url':url,'expires':expires}))
else:
    print('请打开以下一次性注册链接，完成设备确认：\n'+url)
