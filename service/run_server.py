import argparse
import json
from pathlib import Path
import ssl
import uvicorn

from main import make_app
from security import load_keys

parser = argparse.ArgumentParser()
parser.add_argument('--config',default=str(Path(__file__).with_name('config.json')))
args = parser.parse_args()
config = json.loads(Path(args.config).read_text(encoding='utf-8'))
keys = load_keys(Path(config['keys']))
app = make_app(config)
uvicorn.run(app,host=config['host'],port=config['port'],ssl_certfile=config['tls_cert'],
            ssl_keyfile=config['tls_key'],ssl_keyfile_password=keys['tls_password'],
            ssl_version=ssl.PROTOCOL_TLS_SERVER,access_log=False,proxy_headers=False,
            server_header=False,log_level='warning',timeout_keep_alive=10)
