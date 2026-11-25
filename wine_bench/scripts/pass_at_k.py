#!/usr/bin/env python3
"""pass_at_k.py - pass@k of the settings sampled with run_samples.py and judged with eval_samples.py.

    python3 scripts/pass_at_k.py [--k 1,10,100] [--csv]

For a task with n replies of which c pass, the unbiased estimate (Chen et al. 2021, HumanEval) of "at least one of k
randomly drawn replies passes" is   1 - C(n-c, k) / C(n, k);   pass@k is its mean over the tasks.  Computed as the
product  1 - prod_{i=n-c+1..n} (1 - k/i)  (no large binomials).  k > n cannot be estimated and is left out.
compile@k is the same with "compiles" (pass, test_fail, crash, timeout, no_tests) instead of "passes".
Tasks without an evaluation yet are not counted: the "tasks" column says how many the row is based on.
"""
import os, sys, json, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import ROOT

COMPILED = ('pass', 'test_fail', 'crash', 'timeout', 'no_tests')

def at_k(n, c, k):
    if n - c < k: return 1.0
    p = 1.0
    for i in range(n - c + 1, n + 1): p *= 1.0 - k / i
    return 1.0 - p

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', default=os.path.join(ROOT, 'runs')); ap.add_argument('--k', default='1,10,100'); ap.add_argument('--csv', action='store_true')
    a = ap.parse_args(); ks = [int(x) for x in a.k.split(',')]
    rows = []
    for d in sorted(glob.glob(os.path.join(a.runs, 'scenario*', '*', 'samples_eval', '*'))):
        rs = [json.load(open(f)) for f in glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json'))]
        if not rs: continue
        rel = os.path.relpath(d, a.runs).split(os.sep); n = min(r['n'] for r in rs); T = len(rs)
        row = {'scenario': rel[0][8:], 'model': rel[3], 'tasks': T, 'n': n}
        for k in ks:
            if k <= n: row[f'pass@{k}'] = round(100 * sum(at_k(r['n'], r['passed'], k) for r in rs) / T, 1)
        for k in ks:
            if k <= n: row[f'compile@{k}'] = round(100 * sum(at_k(r['n'], r['compiled'], k) for r in rs) / T, 1)
        row['solved'] = sum(1 for r in rs if r['passed']); row['replies'] = sum(r['n'] for r in rs)
        row['passed'] = sum(r['passed'] for r in rs); row['compiled'] = sum(r['compiled'] for r in rs)
        row['no_code'] = sum(r['statuses'].count('no_code') for r in rs); row['distinct'] = sum(r['distinct'] for r in rs)
        rows.append(row)
    if not rows: sys.exit(f'no samples_eval results under {a.runs}')
    cols = list(dict.fromkeys(c for r in rows for c in r))
    if a.csv: print(','.join(cols)); [print(','.join(str(r.get(c, '')) for c in cols)) for r in rows]; return
    w = {c: max(len(c), *(len(str(r.get(c, ''))) for r in rows)) for c in cols}
    print('  '.join(c.ljust(w[c]) for c in cols))
    for r in rows: print('  '.join(str(r.get(c, '')).ljust(w[c]) for c in cols))

if __name__ == '__main__':
    main()
