"""Host regressions for publication changes: no devices, only temporary roots."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class PublicContract(unittest.TestCase):
    def run_isolated(self,source,body,**env):
        with tempfile.TemporaryDirectory() as directory:
            variables=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',DUCK_SOLAR_ROOT=directory,
                           DUCK_SOLAR_B2_CLIENT_DATA=directory,**env)
            prefix='import sys;sys.path.insert(0,'+repr(str(ROOT/source))+');'
            result=subprocess.run([sys.executable,'-c',prefix+body],env=variables,
                                  cwd=directory,text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout

    def test_server_private_defaults_empty_and_config_roundtrip(self):
        self.run_isolated('android-server/app/src/main/python',
            'from ducksolar.config import *;c=load_config();'
            'assert all(not getattr(c,k) for k in ("lwip_ip","dtu_pn","logger_mac","server_url","weather_location_name","auth_token","account_username"));'
            'assert c.weather_latitude is None and c.weather_longitude is None;'
            'assert c.api_port==28766 and c.pv_correction_factor==1 and c.inverter_self_consumption_w==0;'
            'c.lwip_ip="192.0.2.20";c.dtu_pn="Q0000000000000";save_config(c);'
            'd=load_config();assert d.lwip_ip==c.lwip_ip and d.dtu_pn==c.dtu_pn')

    def test_meter_import_has_no_bundled_household_data(self):
        self.run_isolated('android-server/app/src/main/python',
            'from ducksolar.meter_bootstrap import import_snapshot;'
            'assert import_snapshot("unused")["imported"]==0;'
            'from pathlib import Path;assert not Path("unused").exists()')

    def test_android_client_starts_without_profile_or_network(self):
        self.run_isolated('android-client/app/src/main/python',
            'import android_client as c,json;from pathlib import Path;'
            'p=json.loads(c.initialize(str(Path.cwd()/"client")) );'
            'assert p["lan"]==p["remote"]==p["username"]==p["serial"]=="";'
            'assert not p["saved"]')

    def test_pc_profile_has_no_automatic_legacy_import(self):
        self.run_isolated('pc-client',
            'from desktop.settings import *;'
            'assert not migrate_legacy(default_root());'
            'import desktop_client as c,json;'
            'p=json.loads(c.initialize(str(default_root())));assert p["lan"]==p["remote"]==""')

    def test_helper_temp_root_and_loopback_http(self):
        self.run_isolated('pc-helper',
            'from ducksolar.pc_support import LanSupport;from pathlib import Path;'
            'import urllib.request,json;h=LanSupport(Path.cwd()/"helper","127.0.0.1",0);h.start();'
            '\ntry:\n s=json.load(urllib.request.urlopen("http://127.0.0.1:"+str(h.http.server_port)+"/v1/status"));'
            'assert s["helper_version"]=="b2.0.0";assert s["helper_id"]'
            '\nfinally:h.stop()')

    def test_helper_explicit_release_directory_and_traversal_guard(self):
        self.run_isolated('pc-helper',
            'from pathlib import Path;import json,hashlib,zipfile;'
            'from update_server import publish;from ducksolar.pc_support import LanSupport;'
            'r=Path.cwd();releases=r/"public";releases.mkdir();p=releases/"DS_Server_ver.b2.0.0.apk";'
            '\nwith zipfile.ZipFile(p,"w") as z:z.writestr("lib/arm64-v8a/test.so",b"synthetic")'
            '\ne=dict(component="server",file=p.name,version="b2.0.0",version_code=20000,package="ua.ducksolar.b2.server",sha256=hashlib.sha256(p.read_bytes()).hexdigest());'
            '(releases/"release.json").write_text(json.dumps(dict(artifacts=[e])));'
            'publish(r/"runtime",releases);h=LanSupport(r/"runtime","127.0.0.1",0,release_root=releases);h.start();'
            '\ntry:\n assert h.catalog()["updates"][0]["package"]=="ua.ducksolar.b2.server";assert h._apk("server")==p.resolve()'
            '\nfinally:h.stop()')

    def test_b2_installations_are_separate(self):
        for role in ('server','client'):
            project=ROOT/('android-'+role)
            gradle=(project/'app/build.gradle.kts').read_text('utf8')
            self.assertIn('applicationId = "ua.ducksolar.b2.'+role+'"',gradle)
            self.assertIn('versionCode = 20000',gradle)
            self.assertNotIn('storePassword = "',gradle)
        text=(ROOT/'pc-client/desktop/settings.py').read_text('utf8')
        self.assertIn('DuckSolarB2/PCClient',text)
        self.assertIn('else []',text)
        self.assertIn('DuckSolar_B2_Client',(ROOT/'pc-client/client_main.py').read_text('utf8'))

    def test_public_audit(self):
        spec=importlib.util.spec_from_file_location('audit',ROOT/'tools/audit_public.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.audit(ROOT)
        self.assertTrue(result['passed'],result['findings'])


if __name__=='__main__':unittest.main()

