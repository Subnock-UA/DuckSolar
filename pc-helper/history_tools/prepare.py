"""PC utility: use the matching server model; originals remain untouched."""
import argparse,json,sys,time,re
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ducksolar.config import AppConfig
from ducksolar.history_reader import HistoryReader
from ducksolar.prepared_history import export_package,write_json

class PCReader(HistoryReader):
    """Adapt PC backup containers without changing the installed Android code."""
    def available_dates(self, refresh=False):
        if self._dates_cache is not None and not refresh and time.monotonic()-self._dates_cache_at<60:
            return list(self._dates_cache)
        super().available_dates(refresh=True)
        root=Path(self.cfg.root_dir).resolve()
        def safe(p):
            return p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)
        index={day:([p for p in local if safe(p)],[p for p in smart if safe(p)])
               for day,(local,smart) in self._file_index.items()}
        containers=root/'Logs/Inverter/AndroidBackups'
        for installation in sorted(containers.glob('*')):
            if not installation.is_dir() or installation.is_symlink():continue
            for folder in sorted(installation.iterdir()):
                if not folder.is_dir() or folder.is_symlink():continue
                match=re.fullmatch(r'(History_)?(\d{4}-\d{2}-\d{2})\.csv',folder.name,re.I)
                if not match:continue
                try:day=date.fromisoformat(match[2])
                except ValueError:continue
                # Follow the PC service's order: live append backup, latest
                # completed upload, then most recent immutable revision.
                candidate=folder/'Live/current.csv'
                if not safe(candidate):
                    candidate=root/'Data/AndroidSupport/Received'/installation.name/'inverter'/folder.name/'latest.log'
                    try:
                        meta=json.loads(candidate.with_suffix('.revision.json').read_text(encoding='utf-8'))
                        valid=safe(candidate) and meta['bytes']==candidate.stat().st_size
                    except (OSError,ValueError,KeyError,TypeError):valid=False
                    if not valid:
                        revisions=[p for p in folder.glob('*.csv') if safe(p) and re.fullmatch(r'[0-9a-f]{64}\.csv',p.name)]
                        candidate=max(revisions,key=lambda p:(p.stat().st_mtime_ns,p.name)) if revisions else None
                if candidate is None or not safe(candidate):continue
                pair=index.setdefault(day,([],[]));paths=pair[1 if match[1] else 0]
                if candidate not in paths:paths.append(candidate)
        self._file_index={day:pair for day,pair in index.items() if pair[0] or pair[1]}
        self._dates_cache=sorted(self._file_index);self._dates_cache_at=time.monotonic()
        return list(self._dates_cache)

    def find_day_files(self,day):
        local,smart=super().find_day_files(day)
        return [p for p in local if p.is_file()],[p for p in smart if p.is_file()]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True,help='JSON object with the target server model fields, no credentials')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();cfg=AppConfig(root_dir=str(args.root.resolve()))
    model=json.loads(args.model.read_text(encoding='utf-8-sig'))
    keys=dict(HistoryReader(cfg).model_signature())
    if not isinstance(model,dict) or set(model)!=set(keys):parser.error('Model must contain exactly: '+', '.join(keys))
    from ducksolar.preparation_model import apply_model
    apply_model(cfg,model)
    output=args.output or args.root/'Data/AndroidSupport/PreparedHistory/history.zip'
    print('Reusing completed preparation objects; building missing objects and period views.',flush=True)
    from preparation_lock import preparation_lock
    with preparation_lock(args.root):
        result=export_package(PCReader(cfg),output,progress=lambda d,t:print(f'{d}/{t}',flush=True))
        write_json(output.with_suffix('.metadata.json'),dict(result,path=str(output.resolve()),device_id='inverter-1',contract='ducksolar.prepared-history.v1'))
        write_json(args.root/'Data/AndroidSupport/Preparation/result.json',dict(state='completed',sha256=result['sha256']))
    print(json.dumps(result))

if __name__=='__main__':main()
