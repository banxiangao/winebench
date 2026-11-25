"""Dataset access: one JSON per function, named NNNN_<module>_<name>.json."""
import os, glob, json, sys

def record_files(dataset_dir, ids='', limit=0):
    files = sorted(glob.glob(os.path.join(dataset_dir, '[0-9]*.json')))
    if not files: sys.exit(f'no dataset records in {dataset_dir}')
    if ids:
        want = {x.strip().zfill(4) for x in ids.split(',') if x.strip()}
        files = [f for f in files if os.path.basename(f)[:4] in want]
    return files[:limit] if limit else files

def load_records(dataset_dir, ids='', limit=0):
    return [json.load(open(f, encoding='utf-8')) for f in record_files(dataset_dir, ids, limit)]

def select_ids(ids='', limit=0, available=()):
    """same filtering applied to a list of ids (used by run_llm on the prompts directory)"""
    out = sorted(available)
    if ids:
        want = {x.strip().zfill(4) for x in ids.split(',') if x.strip()}
        out = [i for i in out if i in want]
    return out[:limit] if limit else out
