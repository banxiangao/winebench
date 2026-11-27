#!/usr/bin/env python3
"""function_dates.py - when was the implementation of each WineBench function written?

    python3 leakage/function_dates.py --git ~/scratch/winebench-w/wine-history.git [--rev wine-11.19] [--workers 8]

For every sample of the full WineBench set (incoming/.../full/winebench.json: file and line range of the function in
Wine 11.19) the lines of the function are dated with `git blame -w -M -C`: the commit that last changed each line (white
space ignored, lines moved inside a file or copied from another file of the same commit followed back).  The date used
is the COMMIT date - when the line entered Wine's public repository - not the author date.

Writes leakage/function_dates.csv, one line per function:
  id, name, dll, path, line_start, line_end, in_205 (1 if a task of winebench205_doc), n_tests_own, n_tests,
  lines (all lines of the function), code_lines (not blank, not a lone brace, not a pure comment line),
  first_date, median_date, last_date      oldest / median / newest code line
  after_<D>                               share of the code lines committed after date D, for each --date
Only what `git blame` says is recorded here; which functions count as "before" or "after" a model is decided elsewhere.
"""
import os, re, sys, csv, json, argparse, subprocess, datetime, statistics
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIVIAL = re.compile(r'^\s*(?:[{}]\s*;?|/\*.*\*/|//.*|/\*.*|\*.*|.*\*/)?\s*$')          # blank, lone brace, comment-only line

def blame(git, rev, path):
    """-> {line number: (commit, committer time, text)} for the whole file"""
    p = subprocess.run(['git', '--git-dir', git, 'blame', '-w', '-M', '-C', '--line-porcelain', rev, '--', path], capture_output=True)
    if p.returncode: raise RuntimeError(f'git blame {path}: {p.stderr.decode(errors="replace")[:300]}')
    out = {}; sha = None; ctime = None; lineno = None
    for raw in p.stdout.split(b'\n'):
        if raw.startswith(b'\t'):
            out[lineno] = (sha, ctime, raw[1:].decode('utf-8', 'replace'))
        else:
            parts = raw.split(b' ')
            if len(parts) >= 3 and len(parts[0]) == 40 and parts[1].isdigit() and parts[2].isdigit(): sha = parts[0].decode(); lineno = int(parts[2])
            elif parts[0] == b'committer-time': ctime = int(parts[1])
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--git', required=True, help='a repository with the full history of Wine (bare is fine)')
    ap.add_argument('--rev', default='wine-11.19'); ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--full', default=os.path.join(ROOT, 'incoming/winebench_2026-11-24/winebench/full/winebench.json'))
    ap.add_argument('--date', action='append', default=[], help='YYYY-MM-DD, repeatable: a column after_<date> for each')
    ap.add_argument('--out', default=os.path.join(ROOT, 'leakage', 'function_dates.csv'))
    a = ap.parse_args()
    dates = a.date or ['2024-06-30', '2025-08-05', '2026-01-19', '2026-08-13']
    cut = {d: datetime.datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc).timestamp() + 86400 for d in dates}   # after the END of that day
    samples = json.load(open(a.full, encoding='utf-8'))['samples']
    in205 = set()
    for f in os.listdir(os.path.join(ROOT, 'wine_agent/dataset/winebench205_doc')):
        if f[:4].isdigit() and f.endswith('.json'):
            r = json.load(open(os.path.join(ROOT, 'wine_agent/dataset/winebench205_doc', f), encoding='utf-8')); in205.add((r.get('winebench') or {}).get('id'))
    files = sorted({s['location']['path'] for s in samples})
    print(f'{len(samples)} functions in {len(files)} files; rev {a.rev}; dates {dates}', flush=True)
    done = [0]
    def one(path):
        try: b = blame(a.git, a.rev, path)
        except Exception as e: print('  ' + str(e), flush=True); b = None
        done[0] += 1
        if done[0] % 50 == 0: print(f'  {done[0]}/{len(files)} files', flush=True)
        return path, b
    with ThreadPoolExecutor(max_workers=a.workers) as ex: blames = dict(ex.map(one, files))
    day = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d')
    rows = []; bad_name = 0; no_blame = 0
    for s in samples:
        loc = s['location']; b = blames.get(loc['path'])
        row = dict(id=s['id'], name=s['name'], dll=s['dll'], path=loc['path'], line_start=loc['line_start'], line_end=loc['line_end'], in_205=int(s['id'] in in205),
                   n_tests_own=s['tests'].get('n_tests_own'), n_tests=s['tests'].get('n_tests'))
        if not b: no_blame += 1; rows.append(row); continue
        lines = [b[i] for i in range(loc['line_start'], loc['line_end'] + 1) if i in b]
        head = ' '.join(x[2] for x in [b[i] for i in range(max(1, loc['line_start'] - 2), min(loc['line_start'] + 6, loc['line_end'] + 1)) if i in b])
        if not re.search(r'\b' + re.escape(s['name'].split('@')[0]) + r'\b', head) and not re.search(r'\b\w*' + re.escape(s['name'][-8:]), head): bad_name += 1; row['check'] = 'name not at line_start'
        code = [x for x in lines if not TRIVIAL.match(x[2])] or lines
        ts = sorted(x[1] for x in code)
        row.update(lines=len(lines), code_lines=len(code), commits=len({x[0] for x in code}), first_date=day(ts[0]), median_date=day(statistics.median_low(ts)), last_date=day(ts[-1]))
        for d in dates: row['after_' + d] = round(sum(1 for t in ts if t >= cut[d]) / len(ts), 3)
        rows.append(row)
    cols = ['id', 'name', 'dll', 'path', 'line_start', 'line_end', 'in_205', 'n_tests_own', 'n_tests', 'lines', 'code_lines', 'commits', 'first_date', 'median_date', 'last_date'] \
           + ['after_' + d for d in dates] + ['check']
    with open(a.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    print(f'wrote {a.out}: {len(rows)} functions; no blame for {no_blame}; function name not found at its line_start in {bad_name}')
    ok = [r for r in rows if 'last_date' in r]
    for d in dates:
        k = 'after_' + d
        print(f'  {d}: untouched since (0 % newer) {sum(1 for r in ok if r[k] == 0)};  some newer {sum(1 for r in ok if 0 < r[k] < 0.5)};  >= 50 % newer {sum(1 for r in ok if 0.5 <= r[k] < 1)};  '
              f'entirely newer {sum(1 for r in ok if r[k] == 1)}   | of the 205: 0 % {sum(1 for r in ok if r["in_205"] and r[k] == 0)}, >= 50 % {sum(1 for r in ok if r["in_205"] and r[k] >= 0.5)}')

if __name__ == '__main__':
    main()
