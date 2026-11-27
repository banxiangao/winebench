#!/usr/bin/env python3
"""assemble.py - the two datasets of the leakage experiment, from the checked candidates.

    python3 leakage/assemble.py

Pairs: every usable NEW function with its best usable OLD partner (rank 1; rank 2 if rank 1 cannot be used).  A NEW
function without a usable partner is left out, so both datasets have the same number of tasks and task NNNN of one is
the partner of task NNNN of the other.
Writes  wine_agent/dataset/leak2024_new/  and  wine_agent/dataset/leak2024_old/  (records renumbered 0001.., docs/,
manifest.json) and leakage/pairs.csv.
"""
import os, csv, json, glob, shutil, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def checked(g): return list(csv.DictReader(open(os.path.join(ROOT, 'leakage/candidates', g, 'candidates_checked.csv'), encoding='utf-8')))
def records(g):
    out = {}
    for f in glob.glob(os.path.join(ROOT, 'leakage/candidates', g, 'dataset', '[0-9][0-9][0-9][0-9]_*.json')):
        r = json.load(open(f, encoding='utf-8')); out[r['winebench']['id']] = (f, r)
    return out

def put(g, k, f, r, extra):
    """copy record r as task k of group g, with its documentation pages"""
    src = os.path.dirname(f); dst = os.path.join(ROOT, 'wine_agent/dataset', f'leak2024_{g}'); os.makedirs(os.path.join(dst, 'docs'), exist_ok=True)
    old = r['id']; new = f'{k:04d}'; r = json.loads(json.dumps(r)); r['id'] = new
    for d in r.get('docs') or []:
        fn = os.path.basename(d['file']); fn2 = new + fn[len(old):] if fn.startswith(old) else new + '_' + fn
        shutil.copyfile(os.path.join(src, d['file']), os.path.join(dst, 'docs', fn2)); d['file'] = 'docs/' + fn2
    r['leakage'] = extra
    name = new + os.path.basename(f)[4:]
    json.dump(r, open(os.path.join(dst, name), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return name

def main():
    new = [r for r in checked('new') if r['usable'] == '1']; oldc = checked('old'); rn = records('new'); ro = records('old')
    by_pair = collections.defaultdict(list)
    for r in oldc:
        if r['usable'] == '1': by_pair[r['pair']].append(r)
    for g in ('new', 'old'):
        d = os.path.join(ROOT, 'wine_agent/dataset', f'leak2024_{g}')
        if os.path.isdir(d): shutil.rmtree(d)
    full = {s['id']: s for s in json.load(open(os.path.join(ROOT, 'leakage/old_candidates.json'), encoding='utf-8'))['samples']}
    pairs = []; dropped = 0; k = 0; man = {'new': [], 'old': []}
    for r in sorted(new, key=lambda r: r['winebench_id']):
        cands = sorted(by_pair.get(r['winebench_id'], []), key=lambda o: full[o['winebench_id']]['subset']['rank'])
        if not cands: dropped += 1; continue
        o = cands[0]; k += 1
        fn_, rec_n = rn[r['winebench_id']]; fo_, rec_o = ro[o['winebench_id']]
        a = put('new', k, fn_, rec_n, dict(group='new', cutoff='2024-06-30', partner=o['winebench_id'], share_after_cutoff=float(r['share_after_cutoff']), last_date=r['last_date']))
        b = put('old', k, fo_, rec_o, dict(group='old', cutoff='2024-06-30', partner=r['winebench_id'], share_after_cutoff=0.0, last_date=o['last_date'],
                                           partner_rank=full[o['winebench_id']]['subset']['rank'], distance=full[o['winebench_id']]['subset']['distance']))
        man['new'].append(a); man['old'].append(b)
        pairs.append(dict(task=f'{k:04d}', new=r['function'], old=o['function'], category_new=r['category'], category_old=o['category'], code_lines_new=r['code_lines'], code_lines_old=o['code_lines'],
                          loc_new=r['loc'], loc_old=o['loc'], tests_new=r['n_tests_own'], tests_old=o['n_tests_own'], usable_test_files_new=r['usable_test_files'], usable_test_files_old=o['usable_test_files'],
                          share_after_cutoff_new=r['share_after_cutoff'], last_date_new=r['last_date'], last_date_old=o['last_date'], partner_rank=full[o['winebench_id']]['subset']['rank']))
    for g in ('new', 'old'):
        json.dump(collections.OrderedDict(count=len(man[g]), group=g, cutoff='2024-06-30', source=f'leakage/{g}_candidates.json, leakage/pairs.csv', records=man[g]),
                  open(os.path.join(ROOT, 'wine_agent/dataset', f'leak2024_{g}', 'manifest.json'), 'w', encoding='utf-8'), indent=1)
    with open(os.path.join(ROOT, 'leakage', 'pairs.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, list(pairs[0])); w.writeheader(); w.writerows(pairs)
    print(f'{len(pairs)} pairs -> wine_agent/dataset/leak2024_new, leak2024_old, leakage/pairs.csv;  usable NEW functions without a usable partner: {dropped}')
    med = lambda xs: sorted(xs)[len(xs) // 2]
    for g in ('new', 'old'):
        c = [int(p[f'code_lines_{g}'] or 0) for p in pairs]; t = [int(p[f'tests_{g}'] or 0) for p in pairs]; l = [int(p[f'loc_{g}'] or 0) for p in pairs]
        print(f'  {g}: lines median {med(l)}, mean {sum(l) / len(l):.1f};  code lines median {med(c)}, mean {sum(c) / len(c):.1f};  own tests median {med(t)}, mean {sum(t) / len(t):.1f}')
    print('  same category in ' + str(sum(1 for p in pairs if p['category_new'] == p['category_old'])) + f' of {len(pairs)} pairs; partner of rank 1 in ' + str(sum(1 for p in pairs if str(p['partner_rank']) == '1')))
    print('  by category: ' + '; '.join(f'{k} {v}' for k, v in collections.Counter(p['category_new'] for p in pairs).most_common()))

if __name__ == '__main__':
    main()
