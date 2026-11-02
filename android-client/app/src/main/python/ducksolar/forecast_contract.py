"""Server-side forecast analysis v2+ is authoritative, including future compatible revisions."""
def has_server_analysis(result):
 version=result.get('forecast_analysis_version')
 return isinstance(version,int) and not isinstance(version,bool) and version>=2
