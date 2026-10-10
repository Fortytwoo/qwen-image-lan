import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

from security import initialize_keys, atomic_write

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8'))

def configure(args):
    root=Path(args.root).resolve()
    host=ipaddress.ip_address(args.host)
    network=ipaddress.ip_network(args.network,strict=True)
    if host.version!=4 or network.version!=4 or host not in network or not any(host in item and network.subnet_of(item) for item in PRIVATE_NETWORKS):
        raise ValueError('Host and Network must describe one private IPv4 LAN or loopback subnet.')
    rp_id=args.rp_id.lower().rstrip('.')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}',rp_id):
        raise ValueError('RP ID must be a DNS hostname, such as computer-name.local; IP addresses are not supported.')
    if not (1024<=args.port<=65535 and 1024<=args.engine_port<=65535) or args.port==args.engine_port:
        raise ValueError('Choose two different unprivileged ports.')
    if not 1<=args.max_vram<=128 or not 1<=args.threads<=128:
        raise ValueError('Invalid VRAM budget or thread count.')
    config={
        'host':str(host),'port':args.port,'network':str(network),
        'hosts':list(dict.fromkeys([str(host),'localhost',socket.gethostname().lower(),rp_id])),
        'backend':f'http://127.0.0.1:{args.engine_port}','keys':str(root/'private/keys.dpapi'),
        'archive':str(root/'private/archive'),'passkeys':str(root/'private/passkeys.dpapi'),
        'webui':str(root.parent/'webui-turbo.html'),'rp_id':rp_id,'origin':f'https://{rp_id}:{args.port}',
        'tls_cert':str(root/'certs/server.pem'),'tls_key':str(root/'private/server-key.encrypted.pem'),
        'ca_pem':str(root/'certs/ca.pem'),'ca_der':str(root/'certs/Qwen-LAN-CA.cer'),
        'engine':{'port':args.engine_port,'max_vram':args.max_vram,'threads':args.threads},
    }
    config_path=root/'config.json'
    if config_path.exists():
        previous=json.loads(config_path.read_text(encoding='utf-8'))
        if previous!=config:
            raise ValueError('Existing configuration differs. Installation stopped; keys, RP ID and data were preserved. Use a new directory or perform an explicit reviewed migration.')
    private=root/'private'
    private.mkdir(parents=True,exist_ok=True)
    sid=subprocess.check_output(['powershell.exe','-NoProfile','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True).strip()
    if not re.fullmatch(r'S-1-5-[0-9-]+',sid):
        raise RuntimeError('Could not determine the current Windows user SID.')
    subprocess.run(['icacls.exe',str(private),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],
                   check=True,stdout=subprocess.DEVNULL)
    keys=initialize_keys(private/'keys.dpapi')
    if any(name in keys for name in ('password','password_hash','password_salt')):
        raise ValueError('This directory contains a legacy password deployment. Explicit migration is required.')
    certs=root/'certs'
    certs.mkdir(exist_ok=True)
    password=keys['tls_password'].encode()
    ca_path=certs/'ca.pem'
    now=datetime.now(timezone.utc)
    if ca_path.exists():
        ca=x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key=serialization.load_pem_private_key((private/'ca-key.encrypted.pem').read_bytes(),password)
        if ca.not_valid_after_utc<=now+timedelta(days=2):
            raise ValueError('The private CA is expiring. Renew and redistribute it through an explicit migration.')
    else:
        if (private/'ca-key.encrypted.pem').exists():
            raise ValueError('Incomplete CA state; preserve files and repair before installing.')
        ca_key=ec.generate_private_key(ec.SECP256R1())
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Qwen Image LAN Private CA')])
        ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,content_commitment=False,
                data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=False,decipher_only=False),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False).sign(ca_key,hashes.SHA256()))
        atomic_write(private/'ca-key.encrypted.pem',ca_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(password)))
        atomic_write(ca_path,ca.public_bytes(serialization.Encoding.PEM))
        atomic_write(certs/'Qwen-LAN-CA.cer',ca.public_bytes(serialization.Encoding.DER))
    leaf_path=certs/'server.pem'
    leaf=x509.load_pem_x509_certificate(leaf_path.read_bytes()) if leaf_path.exists() else None
    if leaf and leaf.not_valid_after_utc>now+timedelta(days=7):
        names=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if rp_id not in names.get_values_for_type(x509.DNSName) or host not in names.get_values_for_type(x509.IPAddress):
            raise ValueError('Existing certificate does not match this configuration. No certificate was replaced.')
    else:
        key_path=private/'server-key.encrypted.pem'
        leaf_key=serialization.load_pem_private_key(key_path.read_bytes(),password) if key_path.exists() else ec.generate_private_key(ec.SECP256R1())
        leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,rp_id)]))
            .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(host),x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
                x509.DNSName('localhost'),x509.DNSName(rp_id)]),critical=False)
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,content_commitment=False,
                data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=False,decipher_only=False),critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False).sign(ca_key,hashes.SHA256()))
        if not key_path.exists():
            atomic_write(key_path,leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password)))
        atomic_write(leaf_path,leaf.public_bytes(serialization.Encoding.PEM))
    if not config_path.exists():
        atomic_write(config_path,json.dumps(config,indent=2).encode('utf-8'))
    return {'url':config['origin']+'/','scope':'lan-only','authentication':'passkey',
        'ca_sha256':ca.fingerprint(hashes.SHA256()).hex(),'certificate_expires':leaf.not_valid_after_utc.isoformat()}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--network',required=True)
    parser.add_argument('--rp-id',required=True)
    parser.add_argument('--port',type=int,default=8443)
    parser.add_argument('--engine-port',type=int,default=1235)
    parser.add_argument('--max-vram',type=float,default=8)
    parser.add_argument('--threads',type=int,default=8)
    print(json.dumps(configure(parser.parse_args()),indent=2))
