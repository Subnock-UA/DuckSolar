"""Copy the single reviewed catalog to each self-contained build component."""
from pathlib import Path
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
TARGETS=[
    ROOT/'android-server/lan-support/src/main/assets/ducksolar_en.json',
    ROOT/'android-client/lan-support/src/main/assets/ducksolar_en.json',
    ROOT/'pc-client/locale/en.json',
    ROOT/'pc-helper/locale/en.json',
]

def main():
    source=ROOT/'localization/en.json'
    value=json.loads(source.read_text('utf8'))
    assert value and all(isinstance(k,str) and isinstance(v,str) and v for k,v in value.items())
    for path in TARGETS:
        path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
    print('Catalog synchronized:',len(value),'messages,',len(TARGETS),'components')

if __name__=='__main__':main()

