#!/usr/bin/env python3
"""select_new.py - the "new" candidates of the leakage experiment: functions written after a model's training cutoff.

    python3 leakage/select_new.py [--cutoff 2024-06-30] [--share 0.5]

A function is NEW when at least --share of its code lines were committed to Wine after --cutoff
(leakage/function_dates.csv, column after_<cutoff>).  Functions whose line range could not be confirmed are left out.
Writes
  leakage/new_candidates.json     the candidates in the format of winebench_subset.json (for vulcan/build_dataset.sbatch)
  leakage/new_doc_pages.tsv       repository <tab> path of every Microsoft documentation page they need (at most 2 per function)
"""
import os, csv, json, argparse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL = os.path.join(ROOT, 'incoming/winebench_2026-11-24/winebench/full')
REPO = {'win32': 'sdk-api', 'ddi': 'windows-driver-docs-ddi', 'crt': 'cpp-docs', 'win32-conceptual': 'win32', 'win32-gdiplus-flat': 'win32'}
PREF = {'win32': 0, 'ddi': 1, 'crt': 2, 'win32-conceptual': 3, 'win32-gdiplus-flat': 4}

def doc_pages(s, by_name, by_url, max_pages=2):
    """the pages build_subset_dataset.py attaches to a function (same rule) -> [(repo, path)]"""
    name = s['name']; url0 = (s.get('doc') or {}).get('url', ''); rows = []
    r0 = next((r for r in by_name.get(name.lower(), []) if r['url'] == url0), None) or by_url.get(url0)
    if r0: rows.append(r0)
    for r in sorted(by_name.get(name.lower(), []), key=lambda r: (PREF.get(r['source'], 9), r['url'])):
        if all(r['url'] != x['url'] for x in rows): rows.append(r)
    return [(REPO.get(r['source'], r['source']), r['doc_path']) for r in rows[:max_pages]]

def load_index():
    csv.field_size_limit(10 ** 9); by_name = collections.defaultdict(list); by_url = {}
    with open(os.path.join(FULL, 'msdocs_index.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f): by_name[r['name_lower']].append(r); by_url.setdefault(r['url'], r)
    return by_name, by_url

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cutoff', default='2024-06-30'); ap.add_argument('--share', type=float, default=0.5)
    a = ap.parse_args(); col = 'after_' + a.cutoff
    dates = {r['id']: r for r in csv.DictReader(open(os.path.join(ROOT, 'leakage', 'function_dates.csv'), encoding='utf-8'))}
    full = json.load(open(os.path.join(FULL, 'winebench.json'), encoding='utf-8'))
    by_name, by_url = load_index()
    picked = []; pages = collections.OrderedDict(); nodoc = 0
    for s in full['samples']:
        d = dates.get(s['id'])
        if not d or d.get('check') or d.get(col) in ('', None) or float(d[col]) < a.share: continue
        pg = doc_pages(s, by_name, by_url)
        if not pg: nodoc += 1
        t = collections.OrderedDict(s)
        t['subset'] = dict(selected_by=f'leakage experiment, NEW group: >= {a.share:.0%} of the code lines committed after {a.cutoff}', group='new', cutoff=a.cutoff,
                           share_after_cutoff=float(d[col]), first_date=d['first_date'], median_date=d['median_date'], last_date=d['last_date'], code_lines=int(d['code_lines']))
        picked.append(t)
        for p in pg: pages[p] = 1
    picked.sort(key=lambda s: s['id'])
    out = collections.OrderedDict(n_samples=len(picked), wine_version=full.get('wine_version'),
                                  subset_rule=dict(group='new', cutoff=a.cutoff, min_share_after_cutoff=a.share, source='winebench.json + leakage/function_dates.csv'), samples=picked)
    json.dump(out, open(os.path.join(ROOT, 'leakage', 'new_candidates.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    with open(os.path.join(ROOT, 'leakage', 'new_doc_pages.tsv'), 'w', encoding='utf-8') as f:
        for repo, path in pages: f.write(f'{repo}\t{path}\n')
    cat = collections.Counter(s['category']['l1'] for s in picked); rep = collections.Counter(r for r, _ in pages)
    print(f'{len(picked)} new candidates (cutoff {a.cutoff}, share >= {a.share}); without a documentation page in the index: {nodoc}')
    print('by category: ' + '; '.join(f'{k} {v}' for k, v in cat.most_common()))
    print(f'documentation pages needed: {len(pages)} (' + ', '.join(f'{k} {v}' for k, v in rep.most_common()) + ')')

if __name__ == '__main__':
    main()
