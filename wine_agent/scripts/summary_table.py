#!/usr/bin/env python3
"""summary_table.py - one table over every run: scenario x stage x (architect model ->) programmer model.

    python3 scripts/summary_table.py              # text table
    python3 scripts/summary_table.py --csv > runs/summary.csv

Columns: scenario, stage, from (the upstream model whose replies fed the stage, '-' for the first stage),
model (the model queried), total, ok (format_ok), trunc, err, prompt/completion tokens.
"""
import os, sys, json, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import ROOT
from bench import report

def rows(runs):
    for sdir in sorted(glob.glob(os.path.join(runs, 'scenario*'))):
        for mdir in sorted(glob.glob(os.path.join(sdir, '*', 'responses', '*')) + glob.glob(os.path.join(sdir, '*', 'from_*', 'responses', '*'))):
            if not os.path.isdir(mdir): continue
            rel = os.path.relpath(mdir, sdir).split(os.sep)             # stage[/from_x]/responses/model
            stage, frm = rel[0], (rel[1][5:] if rel[1].startswith('from_') else '-')
            s = report.summarize(mdir)
            yield dict(scenario=os.path.basename(sdir)[8:], stage=stage, **{'from': frm}, model=s['model'], total=s['total'],
                       ok=s['format_ok'], first_try=s.get('first_try_ok', ''), retried=s.get('retried', ''), trunc=s['truncated'], err=s['errors'],
                       prompt_tok=s['prompt_tokens'], completion_tok=s['completion_tokens'])

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', default=os.path.join(ROOT, 'runs')); ap.add_argument('--csv', action='store_true')
    a = ap.parse_args()
    rs = list(rows(a.runs))
    if not rs: sys.exit(f'no responses under {a.runs}')
    cols = list(rs[0])
    if a.csv:
        print(','.join(cols)); [print(','.join(str(r[c]) for c in cols)) for r in rs]; return
    w = {c: max(len(c), *(len(str(r[c])) for r in rs)) for c in cols}
    print('  '.join(c.ljust(w[c]) for c in cols))
    for r in rs: print('  '.join(str(r[c]).ljust(w[c]) for c in cols))

if __name__ == '__main__':
    main()
