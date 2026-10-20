import json
from pathlib import Path
for name in ['images','services','runtime','messaging','controlplane']:
    result=json.loads((Path('/reports/labs')/(name+'.json')).read_text())
    assert result['status']=='passed', name+' did not pass'
print('Docker and Redpanda independent evidence verified')
