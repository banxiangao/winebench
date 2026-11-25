#!/usr/bin/env python3
"""rename_model.py - rename a model alias everywhere under runs/ (folders and the fields inside the replies).

    python3 scripts/rename_model.py deepseek deepseek-v4-flash
    python3 scripts/rename_model.py deepseek deepseek-v4-flash --model-id deepseek-chat   # also record the model id used

Renames  runs/*/<stage>/responses/<old>/            -> responses/<new>/
         runs/*/<stage>/from_<old>/                  -> from_<new>/
and sets model / from_model (and model_id if given) inside every <id>.json and summary.json.
Then rename the [[models]] block in scenarios/models.toml by hand (name = "<new>").
"""
import os, sys, json, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import ROOT

def fix_json(f, old, new, model_id):
    r = json.load(open(f, encoding='utf-8')); changed = False
    for k in ('model', 'from_model'):
        if r.get(k) == old: r[k] = new; changed = True
    if model_id and r.get('model') == new and not r.get('model_id'): r['model_id'] = model_id; changed = True
    if changed: json.dump(r, open(f, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return changed

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old'); ap.add_argument('new'); ap.add_argument('--model-id', default='')
    ap.add_argument('--runs', default=os.path.join(ROOT, 'runs'))
    a = ap.parse_args()
    moved = edited = 0
    for d in sorted(glob.glob(os.path.join(a.runs, '**', 'responses', a.old), recursive=True)):
        os.rename(d, os.path.join(os.path.dirname(d), a.new)); moved += 1
    for d in sorted(glob.glob(os.path.join(a.runs, '**', 'from_' + a.old), recursive=True)):
        os.rename(d, os.path.join(os.path.dirname(d), 'from_' + a.new)); moved += 1
    for f in glob.glob(os.path.join(a.runs, '**', '*.json'), recursive=True):
        edited += fix_json(f, a.old, a.new, a.model_id)
    print(f'{moved} folders renamed, {edited} json files updated; now set name = "{a.new}" in scenarios/models.toml')

if __name__ == '__main__':
    main()
