import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('downloads',ROOT/'scripts/download_models.py')
downloads=importlib.util.module_from_spec(spec);spec.loader.exec_module(downloads)

class InstallationTests(unittest.TestCase):
    def test_verified_existing_and_conflicting_download(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'model.gguf';path.write_bytes(b'test-only-payload')
            item={'url':'https://github.com/example/model','name':path.name,'size':path.stat().st_size,
                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            with patch('urllib.request.urlopen') as network:
                downloads.download(item,path)
                network.assert_not_called()
                item['sha256']='0'*64
                with self.assertRaises(ValueError):downloads.download(item,path)
                self.assertEqual(path.read_bytes(),b'test-only-payload')
                network.assert_not_called()

    def test_archive_traversal_and_conflicting_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'engine.zip';destination=root/'engine'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt','bad')
            with self.assertRaises(ValueError):downloads.extract(archive,destination)
            self.assertFalse((root/'escape.txt').exists())
            with zipfile.ZipFile(archive,'w') as z:z.writestr('engine.txt','expected')
            downloads.extract(archive,destination);downloads.extract(archive,destination)
            (destination/'engine.txt').write_text('user-change')
            with self.assertRaises(ValueError):downloads.extract(archive,destination)
            self.assertEqual((destination/'engine.txt').read_text(),'user-change')

    def test_setup_spaces_idempotence_and_config_mismatch(self):
        with tempfile.TemporaryDirectory(prefix='qwen install with spaces ') as temp:
            service=Path(temp)/'service'
            command=[sys.executable,str(ROOT/'service/setup_service.py'),'--root',str(service),
                '--host','127.0.0.1','--network','127.0.0.0/8','--rp-id','qwen-test.local',
                '--port','9443','--engine-port','1236']
            first=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(first.returncode,0,first.stderr)
            snapshots={path.relative_to(service):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in service.rglob('*') if path.is_file()}
            second=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(second.returncode,0,second.stderr)
            self.assertEqual(snapshots,{path.relative_to(service):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in service.rglob('*') if path.is_file()})
            changed=command.copy();changed[changed.index('qwen-test.local')]='different.local'
            rejected=subprocess.run(changed,capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(rejected.returncode,0)
            self.assertEqual(snapshots,{path.relative_to(service):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in service.rglob('*') if path.is_file()})
            config=json.loads((service/'config.json').read_text(encoding='utf-8'))
            self.assertEqual(config['backend'],'http://127.0.0.1:1236')
            self.assertEqual(config['origin'],'https://qwen-test.local:9443')

    def test_localized_vendor_turbo_and_canonical_redirect(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'ui.html'
            result=subprocess.run([sys.executable,str(ROOT/'scripts/localize_webui.py'),
                '--input',str(ROOT/'vendor/webui.html'),'--output',str(output),'--origin','https://qwen-test.local:9443'],
                capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            text=output.read_text(encoding='utf-8')
            self.assertIn('Qwen-Image 本地生图',text)
            self.assertIn('https://qwen-test.local:9443/',text)
            self.assertIn('custom_sigmas:[1.0,0.978453',text)
            self.assertIn('const cu=[]',text)

if __name__=='__main__':unittest.main(verbosity=2)
