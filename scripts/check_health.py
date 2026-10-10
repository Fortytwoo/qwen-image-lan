import json
from pathlib import Path
import ssl
import sys
import httpx

config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
with httpx.Client(verify=ssl.create_default_context(cafile=config['ca_pem']),trust_env=False,timeout=4) as client:
    response=client.get(config['origin']+'/health')
    response.raise_for_status()
    data=response.json()
    assert data['authentication']=='passkey' and data['encrypted_archive'] and data['scope']=='lan-only'
print('Verified HTTPS health: '+config['origin'])
