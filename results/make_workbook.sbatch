#!/bin/bash
#SBATCH --job-name=wb-workbook
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=0:10:00
#SBATCH --output=vulcan/logs/%x-%j.out
# make_workbook.sbatch - write results/WineBench_results.xlsx from the result files.   cd .../WineBench && sbatch results/make_workbook.sbatch
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4
V=${SLURM_TMPDIR:-/tmp}/wbxl-$SLURM_JOB_ID; python -m venv "$V" && source "$V/bin/activate" && pip install --no-index -q xlsxwriter openpyxl
cd "${SLURM_SUBMIT_DIR:-$PWD}" && python results/make_workbook.py && python - <<'PY'
# read the workbook back: every formula must carry a stored value, and the key numbers must be those of the result tables
import csv, openpyxl
f = 'results/WineBench_results.xlsx'
a = openpyxl.load_workbook(f); b = openpyxl.load_workbook(f, data_only=True)
nform = nmiss = 0
for ws in a.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith('='):
                nform += 1
                v = b[ws.title][c.coordinate].value
                if v is None or (isinstance(v, str) and v.startswith('#')): nmiss += 1; print('  no value / error:', ws.title, c.coordinate, c.value, v)
print(f'sheets: {[ws.title for ws in a.worksheets]}')
print(f'formulas: {nform}; without a stored value or with an error: {nmiss}')
ag = b['Agent']; t = {(r['scenario'], r['stage'], r['model']): r for r in csv.DictReader(open('wine_agent/results/table.csv'))}; bad = 0; n = 0
for row in ag.iter_rows(min_row=4, values_only=True):
    k = (str(row[0]), row[1], row[2])
    if k in t:
        n += 1; r = t[k]
        if not (row[5] == int(r['passed']) and row[14] == int(r['compiled']) and row[12] == 205 and abs(row[16] * 100 - float(r['pass%'])) < 0.06 and abs(row[15] * 100 - float(r['compile%'])) < 0.06): bad += 1; print('  MISMATCH', k, row[:17])
print(f'Agent: {n} settings compared with wine_agent/results/table.csv, {bad} mismatches')
pt = b['Agent per task']; last = [r for r in pt.iter_rows(values_only=True) if r[1] and str(r[1]).startswith('Tasks passed')][0]
print('Agent per task, column totals of passes:', [x for x in last[6:24]])
print('             same from table.csv, sorted:', sorted(int(r['passed']) for r in t.values()), '=', sorted(x for x in last[6:24] if isinstance(x, int)))
os_ = b['One-shot']; print('One-shot A pass:', [(r[0], r[1], r[3]) for r in os_.iter_rows(min_row=5, max_row=10, values_only=True)])
PY
python - <<'PY'
# the leakage sheets: the formulas' stored values against a recount of the sheet 'Leakage per pair' and against wine_agent/results/table.csv
import csv, openpyxl
b = openpyxl.load_workbook('results/WineBench_results.xlsx', data_only=True); pp = b['Leakage per pair']; lk = b['Leakage']
rows = list(pp.iter_rows(min_row=5, values_only=True)); data = [r for r in rows if r[0] and str(r[0]).isdigit()]; head2 = [c.value for c in pp[3]]; head3 = [c.value for c in pp[4]]
grp = None; cols = {}
for j, (h2, h3) in enumerate(zip(head2, head3)):
    grp = h2 or grp
    if h3 in ('NEW', 'OLD') and grp: cols[(grp, h3)] = j
t = {(r['scenario'], r['stage']): r for r in csv.DictReader(open('wine_agent/results/table.csv'))}; pk = {r['scenario']: r for r in csv.DictReader(open('wine_bench/results/pass_at_k.csv')) if 'gpt-oss' in r['model']}
bad = 0
for (g, side), j in sorted(cols.items()):
    v = [r[j] for r in data]
    if 'one-shot' in g:
        s = g.split()[1].rstrip(','); n = sum(1 for x in v if x and x > 0); ref = int(pk[f'{s}-{side.lower()}']['solved'])
    else:
        s, h = g.split()[1].rstrip(','), g.split()[2].rstrip(':'); n = v.count('pass'); ref = int(t[(f'{s}-{side.lower()}', h)]['passed'])
    bad += n != ref; print(f'  {g:48s} {side}: {n:3d} of {len(v)}   result table: {ref}' + ('   MISMATCH' if n != ref else ''))
shown = {(r[0], r[1], r[2], r[3]): r for r in lk.iter_rows(values_only=True) if r[2] in ('pass', 'pass@100') and r[3] == 'all pairs'}
for (s, h, m, _), r in sorted(shown.items()):
    g = f'Scenario {s}, one-shot: passing samples of 100' if h == 'one-shot' else f'Scenario {s}, {h}: outcome'
    for side, val in (('NEW', r[5]), ('OLD', r[6])):
        v = [x[cols[(g, side)]] for x in data]; n = sum(1 for x in v if (x == 'pass' if h != 'one-shot' else (x or 0) > 0))
        if abs(val - n / len(v)) > 0.0006: bad += 1; print('  MISMATCH on the sheet Leakage:', s, h, m, side, val, n / len(v))
print(f'Leakage: {len(data)} pairs, {len(cols)} columns, {len(shown)} headline rows checked; mismatches: {bad}')
PY
