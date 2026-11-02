from pathlib import Path
import json
import os
import re
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]


class LanguageContract(unittest.TestCase):
    def run_code(self,code):
        result=subprocess.run([sys.executable,'-c',
            'import sys;sys.path.insert(0,'+repr(str(ROOT/'pc-client'))+');'+code],
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_catalogs_and_placeholders(self):
        source=ROOT/'localization/en.json';catalog=json.loads(source.read_text('utf8'))
        self.assertGreater(len(catalog),1500)
        for key,value in catalog.items():
            self.assertEqual(sorted(re.findall(r'\{#\d+#\}',key)),sorted(re.findall(r'\{#\d+#\}',value)),key)
        for path in ['pc-client/locale/en.json','pc-helper/locale/en.json',
                     'android-client/lan-support/src/main/assets/ducksolar_en.json',
                     'android-server/lan-support/src/main/assets/ducksolar_en.json']:
            self.assertEqual((ROOT/path).read_bytes(),source.read_bytes())

    def test_default_persistence_templates_and_invalid_preference(self):
        self.run_code('from ducksolar import ui_language as L;import tempfile,json;from pathlib import Path;'
            '\nwith tempfile.TemporaryDirectory() as tmp:\n'
            ' assert L.configure(tmp)=="en";assert L.text("Головна")=="Home";'
            'assert L.text("Мережа")=="Grid";assert L.text("Помилка: synthetic")=="Error: synthetic";'
            'assert L.text("profile_123") == "profile_123";'
            'L.set_language("uk");assert L.text("Головна")=="Головна";assert L.configure(tmp)=="uk";'
            '(Path(tmp)/"ui-language.json").write_text(json.dumps({"language":"invalid"}));'
            'assert L.configure(tmp)=="en"')

    def test_tk_display_switch_keeps_input_and_enum_values(self):
        self.run_code('from ducksolar import ui_language as L,tk_language as T;import tkinter as tk;from tkinter import ttk;import tempfile;'
            '\nwith tempfile.TemporaryDirectory() as tmp:\n'
            ' L.configure(tmp);T.install();root=tk.Tk();root.withdraw();'
            'value=tk.StringVar(root,value="Мережа");entry_value=tk.StringVar(root,value="Мережа");'
            'box=ttk.Combobox(root,textvariable=value,values=("Мережа","АКБ"),state="readonly");'
            'entry=ttk.Entry(root,textvariable=entry_value);label=ttk.Label(root,text="Головна");'
            'root.update();assert label.cget("text")=="Home";assert value.get()=="Мережа";'
            'assert box.get()=="Grid";box.current(1);root.update();assert value.get()=="АКБ";'
            'assert entry.get()=="Мережа";L.set_language("uk");T.refresh(root);root.update();'
            'assert label.cget("text")=="Головна";assert value.get()=="АКБ";assert entry.get()=="Мережа";'
            'L.set_language("en");T.refresh(root);root.update();assert box.get()=="Battery";root.destroy()')

    def test_versions_unchanged(self):
        for role in ('client','server'):
            text=(ROOT/f'android-{role}/app/build.gradle.kts').read_text('utf8')
            self.assertIn('versionCode = 20000',text)
            self.assertIn('versionName = "b2.0.0"',text)
        self.assertIn('.'.join(('2','0','0','0')),(ROOT/'pc-client/version_info.txt').read_text('utf8'))


if __name__=='__main__':unittest.main()
