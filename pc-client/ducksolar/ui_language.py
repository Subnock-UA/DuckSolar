"""Presentation-only localization. Raw application values remain canonical."""
from pathlib import Path
from functools import lru_cache
import json
import os
import re
import sys
import threading

SUPPORTED=('en','uk')
_language='en'
_root=None
_catalog=None
_patterns=[]
_phrases=None
_lock=threading.RLock()

def language():return _language

def configure(root):
    global _root,_language
    with _lock:
        _root=Path(root)
        try:value=json.loads((_root/'ui-language.json').read_text('utf8')).get('language')
        except (OSError,ValueError,AttributeError):value='en'
        _language=value if value in SUPPORTED else 'en'
    return _language

def set_language(value):
    global _language
    if value not in SUPPORTED:raise ValueError('Unsupported interface language')
    with _lock:
        if _root is None:raise RuntimeError('Language settings root has not been configured')
        _root.mkdir(parents=True,exist_ok=True)
        temp=_root/'ui-language.tmp'
        temp.write_text(json.dumps({'language':value}),encoding='utf8')
        os.replace(temp,_root/'ui-language.json');_language=value
    return value

def _load():
    global _catalog,_patterns,_phrases
    if _catalog is not None:return
    base=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    data=json.loads((base/'locale/en.json').read_text('utf8'))
    patterns=[]
    for key,value in data.items():
        if '{#' not in key:continue
        pieces=re.split(r'(\{#\d+#\})',key);names=[];parts=[]
        for piece in pieces:
            if re.fullmatch(r'\{#\d+#\}',piece):names.append(piece);parts.append('(.*?)')
            else:parts.append(re.escape(piece))
        patterns.append((sum(len(p) for p in pieces if not p.startswith('{#')),re.compile('^'+''.join(parts)+'$',re.S),value,names))
    _patterns=sorted(patterns,key=lambda row:row[0],reverse=True)
    keys=sorted((k for k in data if '{#' not in k and len(k)>1),key=len,reverse=True)
    _phrases=re.compile('(?<![\\w])(?:'+'|'.join(re.escape(k) for k in keys)+')(?![\\w])')
    _catalog=data

@lru_cache(maxsize=2048)
def _english(value,depth=0):
    _load()
    raw=value.strip()
    if not raw:return value
    prefix=value[:len(value)-len(value.lstrip())];suffix=value[len(value.rstrip()):]
    if raw in _catalog and '{#' not in raw:return prefix+_catalog[raw]+suffix
    if depth<3:
        for _,pattern,target,names in _patterns:
            match=pattern.fullmatch(raw)
            if match:
                result=target
                for name,item in zip(names,match.groups()):result=result.replace(name,_english(item,depth+1))
                return prefix+result+suffix
    value=_phrases.sub(lambda match:_catalog[match.group()],value)
    return re.sub(r'(?<=\d)\s+(В|А|с)(?=$|[\s,;·/])',lambda m:' '+{'В':'V','А':'A','с':'s'}[m[1]],value)

def text(value):
    if value is None:return ''
    value=str(value)
    if _language=='uk' or not re.search('[А-Яа-яІіЇїЄєҐґ]',value):return value
    return _english(value)

