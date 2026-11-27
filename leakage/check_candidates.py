#!/usr/bin/env python3
"""check_candidates.py - which candidate records of the leakage experiment can be used?

    python3 leakage/check_candidates.py leakage/candidates/new [--baseline wine_agent/runs/baseline]

A candidate is usable when its record was built, it has at least one Microsoft documentation page, and at least one of
its test files runs to its summary line on the clean Wine tree (baseline status "ok").
Writes <dir>/candidates_checked.csv and prints the counts.
"""
import os, sys, csv, json, glob, argparse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir'); ap.add_argument('--baseline', default=os.path.join(ROOT, 'wine_agent', 'runs', 'baseline')); ap.add_argument('--list', default='')
    a = ap.parse_args(); d = os.path.abspath(a.dir)
    listed = json.load(open(a.list or os.path.join(ROOT, 'leakage', os.path.basename(d) + '_candidates.json'), encoding='utf-8'))['samples']
    built = {}
    for f in glob.glob(os.path.join(d, 'dataset', '[0-9][0-9][0-9][0-9]_*.json')):
        r = json.load(open(f, encoding='utf-8')); built[(r.get('winebench') or {}).get('id')] = r
    rows = []; why = collections.Counter()
    for s in listed:
        r = built.get(s['id']); sub = s.get('subset') or {}
        row = dict(winebench_id=s['id'], record=r['id'] if r else '', function=f"{s['dll']}!{s['name']}", category=s['category']['l1'], loc=s['loc']['total'], code_lines=sub.get('code_lines', ''),
                   n_tests_own=s['tests'].get('n_tests_own'), share_after_cutoff=sub.get('share_after_cutoff', ''), last_date=sub.get('last_date', ''), pair=sub.get('pair', ''))
        if not r: row.update(usable=0, note='record not built'); why['record not built'] += 1; rows.append(row); continue
        tests = r['native_tests']['files']; st = []
        for t in tests:
            b = os.path.join(a.baseline, t.replace('/', '__')[:-2] + '.json')
            st.append(json.load(open(b))['status'] if os.path.exists(b) else 'not run')
        ok = sum(1 for x in st if x == 'ok'); docs = r.get('docs') or []
        row.update(side=r['function'].get('side', ''), test_files=len(tests), usable_test_files=ok, baseline=' '.join(f'{k}:{v}' for k, v in sorted(collections.Counter(st).items())),
                   doc_pages=len(docs), doc_chars=sum(len(x.get('text') or '') for x in docs), parse_errors=(r.get('meta') or {}).get('parse_errors', ''))
        note = [] if ok else ['no test file runs on the clean tree' if 'not run' not in st else 'baseline not run yet']
        if not docs: note.append('no documentation page')
        row.update(usable=int(not note), note='; '.join(note)); why['; '.join(note) or 'usable'] += 1; rows.append(row)
    cols = ['winebench_id', 'record', 'function', 'category', 'loc', 'code_lines', 'n_tests_own', 'share_after_cutoff', 'last_date', 'pair', 'side', 'test_files', 'usable_test_files', 'baseline',
            'doc_pages', 'doc_chars', 'parse_errors', 'usable', 'note']
    with open(os.path.join(d, 'candidates_checked.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} candidates -> {os.path.join(a.dir, "candidates_checked.csv")}')
    for k, v in why.most_common(): print(f'  {v:4d}  {k}')
    use = [r for r in rows if r['usable']]
    print('usable by category: ' + '; '.join(f'{k} {v}' for k, v in collections.Counter(r['category'] for r in use).most_common()))

if __name__ == '__main__':
    main()
