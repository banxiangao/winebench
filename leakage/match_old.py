#!/usr/bin/env python3
"""match_old.py - the "old" candidates of the leakage experiment: for every usable NEW function, functions that have not
been touched since the model's training cutoff and are as similar as possible.

    python3 leakage/match_old.py [--cutoff 2024-06-30] [--per-new 2]

Pool: functions none of whose code lines were committed after the cutoff (after_<cutoff> = 0), with a confirmed line
range and a documentation page in a repository that can be downloaded.  For each usable NEW function
(leakage/candidates/new/candidates_checked.csv) the --per-new closest unused pool functions are taken:
  same top-level category (required; if the category runs out, any category),
  then the smallest  2*|ln code lines| + |ln (tests+1)| + 0.3 (other DLL) + 0.5 (other side: Unix / PE) + 0.3 (wineserver use differs).
More than one per NEW function are taken so that an OLD function that turns out not to be testable can be replaced.
Writes leakage/old_candidates.json (format of winebench_subset.json; subset.pair = the NEW function, subset.rank = 1, 2, ...)
and leakage/old_doc_pages.tsv.
"""
import os, csv, json, math, argparse, collections
from select_new import doc_pages, load_index, ROOT, FULL

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cutoff', default='2024-06-30'); ap.add_argument('--per-new', type=int, default=2); ap.add_argument('--no-repo', default='cpp-docs')
    a = ap.parse_args(); col = 'after_' + a.cutoff
    dates = {r['id']: r for r in csv.DictReader(open(os.path.join(ROOT, 'leakage', 'function_dates.csv'), encoding='utf-8'))}
    full = json.load(open(os.path.join(FULL, 'winebench.json'), encoding='utf-8')); by_id = {s['id']: s for s in full['samples']}
    by_name, by_url = load_index(); skip = set(a.no_repo.split(','))
    new = [r for r in csv.DictReader(open(os.path.join(ROOT, 'leakage/candidates/new/candidates_checked.csv'), encoding='utf-8')) if r['usable'] == '1']
    pool = {}
    for s in full['samples']:
        d = dates.get(s['id'])
        if not d or d.get('check') or d.get(col) in ('', None) or float(d[col]) != 0: continue
        pg = doc_pages(s, by_name, by_url)
        if not pg or any(r in skip for r, _ in pg[:1]): continue
        pool[s['id']] = (s, pg, d)
    print(f'{len(new)} usable NEW functions; pool of untouched functions with a documentation page: {len(pool)}')
    feat = lambda s: (s['category']['l1'], s['dll'], max(1, s['loc'].get('code') or 1), s['tests'].get('n_tests_own') or 0, bool(s.get('unix_side')), bool(s.get('uses_wineserver')))
    def dist(x, y):
        return 2 * abs(math.log(x[2]) - math.log(y[2])) + abs(math.log(x[3] + 1) - math.log(y[3] + 1)) + (0 if x[1] == y[1] else 0.3) + (0.5 if x[4] != y[4] else 0) + (0.3 if x[5] != y[5] else 0)
    size = collections.Counter(feat(s)[0] for s, _, _ in pool.values())
    order = sorted(new, key=lambda r: (size[by_id[r['winebench_id']]['category']['l1']], r['winebench_id']))      # scarce categories first
    used = set(); picked = []; pages = collections.OrderedDict(); other_cat = 0; dists = []
    for rank in range(1, a.per_new + 1):                                 # every NEW function gets its best partner before anyone gets a second
        for r in order:
            n = by_id[r['winebench_id']]; fn = feat(n)
            cand = [(dist(fn, feat(s)), i) for i, (s, _, _) in pool.items() if i not in used and feat(s)[0] == fn[0]]
            if not cand: cand = [(dist(fn, feat(s)) + 5, i) for i, (s, _, _) in pool.items() if i not in used]; other_cat += 1
            dd, i = min(cand); used.add(i); s, pg, d = pool[i]; dists.append(dd) if rank == 1 else None
            t = collections.OrderedDict(s)
            t['subset'] = dict(selected_by=f'leakage experiment, OLD group: no code line committed after {a.cutoff}; matched to a NEW function', group='old', cutoff=a.cutoff,
                               share_after_cutoff=0.0, first_date=d['first_date'], median_date=d['median_date'], last_date=d['last_date'], code_lines=int(d['code_lines']),
                               pair=n['id'], rank=rank, distance=round(dd, 3))
            picked.append(t)
            for p in pg: pages[p] = 1
    picked.sort(key=lambda s: (s['subset']['pair'], s['subset']['rank']))
    out = collections.OrderedDict(n_samples=len(picked), wine_version=full.get('wine_version'),
                                  subset_rule=dict(group='old', cutoff=a.cutoff, per_new=a.per_new, source='winebench.json + leakage/function_dates.csv, matched to leakage/candidates/new'), samples=picked)
    json.dump(out, open(os.path.join(ROOT, 'leakage', 'old_candidates.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    with open(os.path.join(ROOT, 'leakage', 'old_doc_pages.tsv'), 'w', encoding='utf-8') as f:
        for repo, path in pages: f.write(f'{repo}\t{path}\n')
    dists.sort()
    print(f'{len(picked)} OLD candidates ({a.per_new} per NEW function); matched outside the category: {other_cat}; '
          f'distance of the first partner: median {dists[len(dists) // 2]:.2f}, 90th percentile {dists[int(len(dists) * 0.9)]:.2f}, max {dists[-1]:.2f}')
    for g, rows in (('NEW', [by_id[r['winebench_id']] for r in new]), ('OLD rank 1', [s for s in picked if s['subset']['rank'] == 1])):
        c = sorted(feat(s)[2] for s in rows); t = sorted(feat(s)[3] for s in rows)
        print(f'  {g:10s} n={len(rows)}  code lines median {c[len(c) // 2]}, mean {sum(c) / len(c):.1f};  own tests median {t[len(t) // 2]}, mean {sum(t) / len(t):.1f};  '
              f'Unix side {sum(1 for s in rows if s.get("unix_side"))};  same DLL as partner: {sum(1 for s in rows if g != "NEW" and s["dll"] == by_id[s["subset"]["pair"]]["dll"]) if g != "NEW" else "-"}')
    print(f'documentation pages needed: {len(pages)}')

if __name__ == '__main__':
    main()
