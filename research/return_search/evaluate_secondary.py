"""Evaluate preregistered return leaders; never choose using evaluation returns."""
import json
import hashlib
from research.return_search.run import OUT,ROOT,END_TEST,run_family,HASHES

if __name__=='__main__':
    s=json.loads((OUT/'secondary_selection.json').read_text())
    assert hashlib.sha256((ROOT/'research/return_search/EVALUATION_EXTENSION.md').read_bytes()).hexdigest()==s['extension_sha256']
    folder=OUT/'secondary_evaluation';folder.mkdir(exist_ok=True)
    if (folder/'results.json').exists():raise RuntimeError('secondary evaluation already completed')
    keys=sorted({s['highest_return'],s['highest_fitted_model']});result={}
    for family in sorted({k.split('__')[0] for k in keys}):
        names=[k.split('__',1)[1] for k in keys if k.startswith(family+'__')]
        result.update(run_family(family,END_TEST,names,'2025-07-01',folder))
    (folder/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    (folder/'input_hashes.json').write_text(json.dumps(HASHES,indent=2))
