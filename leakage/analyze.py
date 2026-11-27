#!/usr/bin/env python3
"""analyze.py - the leakage experiment: NEW tasks (written after the model's training cutoff) against their OLD partners.

    python3 leakage/analyze.py [--model gpt-oss-20b]          (as a job: sbatch leakage/analyze.sbatch)

Task NNNN of leak2024_new and task NNNN of leak2024_old are a pair (leakage/pairs.csv).  For every setting that has both
groups evaluated, on the pairs evaluated in both:
  one-shot settings (1.1, 1.2; n samples per task): mean pass@1 / pass@10 / pass@n and compile@k of each group
      (unbiased estimator 1 - C(n-c, k) / C(n, k)); how the tasks spread over the number of passing samples
  agent settings (2.1, 2.2 x mini_swe, openhands): pass and compile rate of each group; the pairs in which only one
      member passed; exact McNemar test on them
  both: how close the submitted code is to Wine's implementation (identical; similarity; "near copy" = similarity of at
      least 0.9) - what a model that has memorised the original would show
  the difference OLD - NEW with a 95 % interval from a paired bootstrap (10,000 resamples of the pairs)
  the headline number (pass@n, pass) again for subsets of the pairs: both functions in the same DLL; NEW function
      entirely / only partly written after the cutoff
Writes leakage/results.txt, leakage/results.csv, leakage/results_tasks.csv (one line per pair: the outcome in every setting)
and leakage/results_by_newness.csv (pass and compile rates of the pairs whose NEW function is entirely / partly new).
"""
import os, csv, json, glob, math, random, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEAR = 0.9
def jload(f):
    try: return json.load(open(f, encoding='utf-8'))
    except Exception: return None
def pass_at_k(n, c, k): return 1.0 if n - c < k else 1.0 - math.comb(n - c, k) / math.comb(n, k)
def mcnemar(b, c):
    """exact two-sided p for b vs c discordant pairs"""
    n = b + c
    if n == 0: return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n)
def boot(old, new, rng, reps=10000):
    """mean(old) - mean(new) over the pairs, with a 95 % percentile interval from resampling the pairs"""
    n = len(old); d = [o - x for o, x in zip(old, new)]; m = sum(d) / n; ms = []
    for _ in range(reps):
        s = 0.0
        for _ in range(n): s += d[rng.randrange(n)]
        ms.append(s / n)
    ms.sort(); return m, ms[int(0.025 * reps)], ms[int(0.975 * reps)]
def sims(e): return [u['similarity'] for u in e.get('unique') or [] if isinstance(u.get('similarity'), (int, float))]

def load(d, key):
    out = {}
    for f in glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json')):
        e = jload(f)
        if e and key in e: out[os.path.basename(f)[:4]] = e
    return out
def agent(scen, harness, model): return {g: load(os.path.join(ROOT, 'wine_agent', 'runs', f'scenario{scen}-{g}', harness, 'eval', model), 'status') for g in ('new', 'old')}
def oneshot(scen, model, n_name): return {g: load(os.path.join(ROOT, 'wine_bench', 'runs', f'scenario{scen}-{g}', 'programmer', 'samples_eval', f'{model}-{n_name}'), 'passed') for g in ('new', 'old')}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='gpt-oss-20b'); ap.add_argument('--samples', default='n100'); ap.add_argument('--seed', type=int, default=20261127)
    a = ap.parse_args(); rng = random.Random(a.seed); rows = []; L = []; N = a.samples[1:]
    P = lambda s='': L.append(s)
    pct = lambda x: f'{100 * x:5.1f}'
    pairs = {p['task']: p for p in csv.DictReader(open(os.path.join(ROOT, 'leakage', 'pairs.csv'), encoding='utf-8'))}
    SUB = [('all pairs', lambda p: True), ('same DLL', lambda p: p['new'].split('!')[0] == p['old'].split('!')[0]), ('other DLL', lambda p: p['new'].split('!')[0] != p['old'].split('!')[0]),
           ('NEW entirely new', lambda p: float(p['share_after_cutoff_new']) >= 0.999), ('NEW partly new', lambda p: float(p['share_after_cutoff_new']) < 0.999)]
    per = {i: {} for i in pairs}                                         # per pair: the outcome in every setting -> results_tasks.csv
    head2 = []                                                           # further metrics for the subset table; after the headline ones so that their intervals stay as they were
    head = []                                                            # (setting, ids, new values, old values) of the headline metric
    def line(scen, h, name, ids, n_, o_, extra='', more=None):
        m, lo, hi = boot(o_, n_, rng)
        P(f'{scen:9} {h:10} {len(ids):5d}  {name:14} {pct(sum(n_) / len(ids))} {pct(sum(o_) / len(ids))}  {100 * m:+6.1f}  [{100 * lo:+5.1f}, {100 * hi:+5.1f}]{extra}')
        r = dict(scenario=scen, harness=h, subset='all pairs', metric=name, pairs=len(ids), new=round(100 * sum(n_) / len(ids), 4), old=round(100 * sum(o_) / len(ids), 4),
                 old_minus_new=round(100 * m, 2), ci_low=round(100 * lo, 2), ci_high=round(100 * hi, 2)); r.update(more or {}); rows.append(r)
    P(f'Leakage experiment, model {a.model}: NEW = at least half of the code lines committed after 2024-06-30, OLD = none (matched partner).')
    P('Differences are OLD - NEW in percentage points, with a 95 % interval from a paired bootstrap.  A model that had memorised the old code')
    P('would do better on OLD and would hand in code closer to the original there.'); P()
    P(f'== one-shot, {N} samples per task')
    P(f'{"scenario":9} {"":10} {"pairs":>5}  {"metric":14} {"NEW":>6} {"OLD":>6}  {"OLD - NEW":>22}')
    for scen in ('1.1', '1.2'):
        d = oneshot(scen, a.model, a.samples); ids = sorted(set(d['new']) & set(d['old']))
        if not ids: P(f'{scen:9} not evaluated yet (new {len(d["new"])}, old {len(d["old"])})'); continue
        mets = [('pass@1', lambda e: pass_at_k(e['n'], e['passed'], 1)), ('pass@10', lambda e: pass_at_k(e['n'], e['passed'], 10)), (f'pass@{N}', lambda e: float(e['passed'] > 0)),
                ('compile@1', lambda e: pass_at_k(e['n'], e['compiled'], 1)), ('compile@10', lambda e: pass_at_k(e['n'], e['compiled'], 10)), (f'compile@{N}', lambda e: float(e['compiled'] > 0)),
                ('identical', lambda e: float(any(u.get('identical') for u in e.get('unique') or []))),
                ('near copy', lambda e: float(any(s >= NEAR for s in sims(e)))),
                ('similarity', lambda e: (lambda s: sum(s) / len(s) if s else 0.0)(sims(e))), ('max similarity', lambda e: max(sims(e) or [0.0]))]
        for name, fn in mets:
            n_ = [fn(d['new'][i]) for i in ids]; o_ = [fn(d['old'][i]) for i in ids]; line(scen, 'one-shot', name, ids, n_, o_)
            if name == f'pass@{N}': head.append((f'{scen} one-shot pass@{N}', ids, n_, o_))
            elif name in ('pass@1', 'pass@10'): head2.append((f'{scen} one-shot {name}', ids, n_, o_))
        for g in ('new', 'old'):
            for i in ids: per[i][f'{scen}_{g}_passed'] = d[g][i]['passed']; per[i][f'{scen}_{g}_compiled'] = d[g][i]['compiled']
        bins = [('0', 0, 0), ('1-9', 1, 9), ('10-49', 10, 49), ('50+', 50, 10 ** 9)]
        for g in ('new', 'old'):
            c = [sum(1 for i in ids if lo <= d[g][i]['passed'] <= hi) for _, lo, hi in bins]
            P(f'{scen:9} tasks by number of passing samples, {g.upper()}: ' + ', '.join(f'{b[0]}: {x}' for b, x in zip(bins, c)))
        P()
    P('== agent')
    P(f'{"scenario":9} {"harness":10} {"pairs":>5}  {"metric":14} {"NEW":>6} {"OLD":>6}  {"OLD - NEW":>22}   only OLD / only NEW, McNemar p')
    COMPILED = ('pass', 'test_fail', 'crash', 'timeout', 'no_tests')
    for scen in ('2.1', '2.2'):
        for h in ('mini_swe', 'openhands'):
            d = agent(scen, h, a.model); ids = sorted(set(d['new']) & set(d['old']))
            if not ids: P(f'{scen:9} {h:10} not evaluated yet (new {len(d["new"])}, old {len(d["old"])})'); continue
            for g in ('new', 'old'):
                for i in ids: per[i][f'{scen}_{h}_{g}'] = d[g][i]['status']; per[i][f'{scen}_{h}_{g}_similarity'] = d[g][i].get('similarity', '')
            mets = [('pass', lambda e: float(e['status'] == 'pass')), ('compiled', lambda e: float(e['status'] in COMPILED)), ('with code', lambda e: float(e['status'] != 'no_code')),
                    ('identical', lambda e: float(bool(e.get('identical')))), ('near copy', lambda e: float((e.get('similarity') or 0.0) >= NEAR)), ('similarity', lambda e: float(e.get('similarity') or 0.0))]
            for name, fn in mets:
                n_ = [fn(d['new'][i]) for i in ids]; o_ = [fn(d['old'][i]) for i in ids]; extra = ''; more = None
                if name in ('pass', 'compiled'):
                    b = sum(1 for x, y in zip(o_, n_) if x and not y); c = sum(1 for x, y in zip(o_, n_) if y and not x)
                    extra = f'   {b} / {c}, p = {mcnemar(b, c):.3f}'; more = dict(only_old=b, only_new=c, mcnemar_p=round(mcnemar(b, c), 4))
                line(scen, h, name, ids, n_, o_, extra, more)
                if name == 'pass': head.append((f'{scen} {h} pass', ids, n_, o_))
            P()
    P('== the headline number on subsets of the pairs (OLD - NEW, percentage points)')
    P(f'{"setting":24} ' + ' '.join(f'{s[0]:>26}' for s in SUB))
    for name, ids, n_, o_ in head + head2:
        cells = []
        for sname, keep in SUB:
            k = [j for j, i in enumerate(ids) if i in pairs and keep(pairs[i])]
            if not k: cells.append(f'{"-":>26}'); continue
            nn = [n_[j] for j in k]; oo = [o_[j] for j in k]; m, lo, hi = boot(oo, nn, rng)
            cells.append(f'{f"{100 * m:+5.1f} [{100 * lo:+5.1f}, {100 * hi:+5.1f}] n={len(k)}":>26}')
            if sname != 'all pairs':
                sc, hh = name.split()[0], name.split()[1]
                rows.append(dict(scenario=sc, harness=hh, subset=sname, metric=name.split()[-1], pairs=len(k), new=round(100 * sum(nn) / len(k), 4), old=round(100 * sum(oo) / len(k), 4),
                                 old_minus_new=round(100 * m, 2), ci_low=round(100 * lo, 2), ci_high=round(100 * hi, 2)))
        P(f'{name:24} ' + ' '.join(cells))
    P(); P('== rates by how new the NEW function is (percent): each group of NEW functions next to its own OLD partners')
    P(f'{"scenario":9} {"":10} {"metric":12} ' + ' '.join(f'{x:>20}' for x in ('entirely new: NEW', 'its OLD partners', 'partly new: NEW', 'its OLD partners')))
    nrows = []
    def by_newness(sc, h, name, val):
        """val(i, g) -> the value of pair i in group g, or None if it was not evaluated"""
        out = []
        for sname, keep in SUB[3:]:
            k = [i for i in sorted(pairs) if keep(pairs[i]) and val(i, 'new') is not None and val(i, 'old') is not None]
            if not k: out += [float('nan')] * 2; continue
            a_ = 100 * sum(val(i, 'new') for i in k) / len(k); b_ = 100 * sum(val(i, 'old') for i in k) / len(k); out += [a_, b_]
            nrows.append(dict(scenario=sc, harness=h, metric=name, subset=sname, pairs=len(k), new=round(a_, 4), old=round(b_, 4)))
        P(f'{sc:9} {h:10} {name:12} ' + ' '.join(f'{x:20.1f}' for x in out))
    for scen in ('1.1', '1.2'):
        for kind, label in (('passed', 'pass'), ('compiled', 'compile')):
            for k_ in (1, 10, int(N)):
                by_newness(scen, 'one-shot', f'{label}@{k_}', lambda i, g, scen=scen, kind=kind, k_=k_: (lambda c: None if c is None else pass_at_k(int(N), int(c), k_))(per[i].get(f'{scen}_{g}_{kind}')))
    for scen in ('2.1', '2.2'):
        for h in ('mini_swe', 'openhands'):
            by_newness(scen, h, 'pass', lambda i, g, scen=scen, h=h: (lambda s: None if s is None else float(s == 'pass'))(per[i].get(f'{scen}_{h}_{g}')))
            by_newness(scen, h, 'compiled', lambda i, g, scen=scen, h=h: (lambda s: None if s is None else float(s in COMPILED))(per[i].get(f'{scen}_{h}_{g}')))
    with open(os.path.join(ROOT, 'leakage', 'results_by_newness.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, ['scenario', 'harness', 'metric', 'subset', 'pairs', 'new', 'old']); w.writeheader(); w.writerows(nrows)
    open(os.path.join(ROOT, 'leakage', 'results.txt'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    cols = ['scenario', 'harness', 'subset', 'metric', 'pairs', 'new', 'old', 'old_minus_new', 'ci_low', 'ci_high', 'only_old', 'only_new', 'mcnemar_p']
    with open(os.path.join(ROOT, 'leakage', 'results.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    base = ['task', 'new', 'old', 'category_new', 'category_old', 'code_lines_new', 'code_lines_old', 'share_after_cutoff_new', 'last_date_new', 'last_date_old']
    extra = sorted({k for v in per.values() for k in v})
    with open(os.path.join(ROOT, 'leakage', 'results_tasks.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, base + extra); w.writeheader()
        for i in sorted(pairs): w.writerow({**{k: pairs[i][k] for k in base}, **per[i]})
    print('\n'.join(L))

if __name__ == '__main__':
    main()
