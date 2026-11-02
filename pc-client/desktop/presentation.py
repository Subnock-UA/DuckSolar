"""Presentation only: transport and JSON exports retain the complete response."""
import copy
TECHNICAL={'contract','audit_id','query_id','server_profile','kind','metric','cache_hit','incremental','reduced','forecast_basis','checkpoint','diagnostics','raw','raw_text','suppress_summary'}
DETAILS={'segments','reference_intervals','calendar_estimate','hourly','delta','rates','taxes','input_parts'}
def visible(value):
 if not isinstance(value,dict):return value
 out=copy.deepcopy(value)
 # The selected finance period has its own card; keep other history periods.
 if isinstance(out.get('selected'),dict) and isinstance(out.get('history'),list):
  selected=out['selected'];key=selected.get('month') or selected.get('delta',{}).get('month')
  out['history']=[r for r in out['history'] if r!=selected and not (key and (r.get('month') or r.get('delta',{}).get('month'))==key)]
 if out.get('segments')==out.get('reference_intervals') and 'reference_intervals' in out:out.pop('segments',None)
 return out
