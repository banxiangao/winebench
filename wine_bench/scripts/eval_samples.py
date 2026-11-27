#!/usr/bin/env python3
"""eval_samples.py - evaluate the N replies per task written by run_samples.py (for pass@k).

    python3 scripts/eval_samples.py --src /w/wine --build /w/wine-build --scenario 1.1 --model qwen3.8-27b-n100 \
            --workers 6 --prefix /w/pfx/wine --runs /w/evalruns --shard 0/4

Every reply is judged exactly as evaluate.py judges a one-shot reply (the same evaluate_record: splice, compile, the
module's Wine tests against the clean-tree baseline, restore) - this script only decides WHAT is evaluated:
  - identical code of the same task is evaluated once and the result counted for every reply that produced it;
  - a reply without usable code is no_code, without building anything;
  - --shard i/m takes every m-th task, so m jobs can share one setting.
Reads  runs/<scenario>/programmer/samples/<model>/<id>.json
Writes runs/<scenario>/programmer/samples_eval/<model>/<id>.json : ONE file per task
       {"n", "statuses": [status of each of the n replies], "passed": c, "unique": [one entry per distinct code]}
Resumable: a task that has its file is skipped; a task is written when all its distinct codes are judged.  Until then
the result of every judged code is appended to samples_eval/<model>/partial/<id>.jsonl (keyed by the hash of the code)
and read back by the next job, so a task that needs more than one job's time still gets done.
One difference from evaluate.py: the test files of a reply are not run past the first one that times out (the reply has
failed either way; a hanging ntdll function would otherwise cost timeout x number of test files - 22 x 300 s for memcpy).
pass and compiled are unaffected; such a reply is "timeout" where a full run could have said "crash".
--runs holds the baselines (runs/baseline, shared) and this run's crash backups (must be private to the job).
"""
import os, sys, json, glob, time, argparse, tempfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as ev
from bench.config import load_scenario, add_scenario_args, ROOT
from bench.dataset import load_records

COMPILED = ('pass', 'test_fail', 'crash', 'timeout', 'no_tests')

def slim(out):
    """what is kept of one evaluate_record result"""
    r = dict(status=out['status'])
    for k in ('identical', 'similarity', 'restore', 'tests_not_run'):
        if k in out: r[k] = out[k]
    if out['status'] == 'splice_fail': r['error'] = (out.get('splice') or {}).get('error', '')[:300]
    c = out.get('compile')
    if c:
        c = c if isinstance(c, dict) else c[-1]
        if not c.get('ok'): r['error'] = (c.get('errors') or ['see the build'])[0][:300]
    if out.get('tests'):
        r['tests'] = [dict(file=t['file'], verdict=t['verdict'], executed=t['executed'], new_failures=t['new_failures'][:20]) for t in out['tests']]
    return r

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--model', required=True, help='folder under samples/, e.g. qwen3.8-27b-n100')
    ap.add_argument('--src', required=True); ap.add_argument('--build', required=True)
    ap.add_argument('--workers', type=int, default=1); ap.add_argument('--jobs', type=int, default=0)
    ap.add_argument('--timeout', type=int, default=300); ap.add_argument('--compile-timeout', type=int, default=1800)
    ap.add_argument('--prefix', default='~/.wine-bench'); ap.add_argument('--own-xvfb', action='store_true')
    ap.add_argument('--runs', default=os.path.join(ROOT, 'runs'))
    ap.add_argument('--shard', default='0/1', help='i/m: the tasks whose position in the task list is i modulo m')
    ap.add_argument('--seconds', type=int, default=0, help='stop starting evaluations after this many seconds')
    ap.set_defaults(stage='programmer')
    a = ap.parse_args()
    a.stop_at_timeout = True; a.rebuild_restore = a.dry_run = a.no_tests = a.no_rerun = a.strict_todo = False; a.spliced_dir = None
    scn = load_scenario(a.scenario); st = scn.stage(a.stage); a.splice_base = st.get('splice_base', 'original')
    stage_dir = scn.out(a.stage); sdir = os.path.join(stage_dir, 'samples', a.model); edir = os.path.join(stage_dir, 'samples_eval', a.model)
    pdir = os.path.join(edir, 'partial'); os.makedirs(pdir, exist_ok=True)
    key = lambda c: hashlib.sha1(c.encode('utf-8', 'surrogatepass')).hexdigest()
    si, sm = (int(x) for x in a.shard.split('/'))
    records = [r for k, r in enumerate(load_records(scn.dataset, a.ids, a.limit)) if k % sm == si]
    bdir = os.path.join(a.runs, 'baseline'); backups = os.path.join(a.runs, 'backups'); os.makedirs(backups, exist_ok=True)
    a.src = os.path.abspath(os.path.expanduser(a.src))

    tasks = {}; items = []; missing = 0; reused = 0                               # id -> state; items = (id, index of the distinct code)
    for rec in records:
        i = rec['id']
        if os.path.exists(os.path.join(edir, i + '.json')): continue
        f = os.path.join(sdir, i + '.json')
        if not os.path.exists(f): missing += 1; continue
        s = json.load(open(f, encoding='utf-8')); codes = []; where = {}; of = []
        for smp in s['samples']:
            c = smp.get('code')
            if not c: of.append(-1); continue
            if c not in where: where[c] = len(codes); codes.append(c)
            of.append(where[c])
        res = [None] * len(codes); pf = os.path.join(pdir, i + '.jsonl')
        if os.path.exists(pf):                                        # judged by an earlier job
            have = {}
            for line in open(pf, encoding='utf-8'):
                try: d = json.loads(line); have[d['key']] = d['result']
                except Exception: pass                                # a line cut off by the job's end
            res = [have.get(key(c)) for c in codes]
        todo_u = [u for u in range(len(codes)) if res[u] is None]; reused += len(codes) - len(todo_u)
        tasks[i] = dict(rec=rec, n=len(s['samples']), of=of, codes=codes, res=res, left=len(todo_u), t0=None)
        items += [(i, u) for u in todo_u]
    n_tasks = len(records); done0 = n_tasks - len(tasks) - missing
    print(f'[{a.model}] shard {a.shard}: {n_tasks} tasks, {done0} already evaluated, {missing} without samples; '
          f'{len(tasks)} tasks to evaluate = {sum(t["n"] for t in tasks.values())} replies, {len(items)} distinct codes to judge ({reused} judged by earlier jobs)', flush=True)

    def finish(i):
        t = tasks[i]; rec = t['rec']; f = rec['function']
        statuses = ['no_code' if u < 0 else t['res'][u]['status'] for u in t['of']]
        uniq = []
        for u, r in enumerate(t['res']): uniq.append(dict(r, count=t['of'].count(u), first=t['of'].index(u)))
        out = dict(id=i, function=f['name'], module=f['module'], file=f['file'], model=a.model, scenario=scn.name, stage=a.stage,
                   n=t['n'], passed=statuses.count('pass'), compiled=sum(1 for x in statuses if x in COMPILED),
                   distinct=len(t['codes']), statuses=statuses, unique=uniq, seconds=round(time.time() - (t['t0'] or time.time()), 1))
        tmp = os.path.join(edir, i + '.json.tmp'); json.dump(out, open(tmp, 'w'), ensure_ascii=False); os.replace(tmp, os.path.join(edir, i + '.json'))
        try: os.remove(os.path.join(pdir, i + '.jsonl'))
        except OSError: pass
        return out

    written = 0
    for i, t in list(tasks.items()):                                  # nothing to build: no reply has code, or all were judged before
        if not t['left']: finish(i); written += 1; del tasks[i]
    if not items:
        print(f'[{a.model}] shard {a.shard}: nothing to build; {done0 + written}/{n_tasks} tasks evaluated', flush=True); return

    trees = ev.make_trees(a)
    for w in trees:
        if not w.ensure_clean(): sys.exit(f'FATAL: {w.src} could not be brought back to a clean state')
    for w in trees: w.ensure_prefix()
    deadline = time.time() + a.seconds if a.seconds else 0; t_start = time.time(); judged = 0

    def one(wine, item):
        i, u = item; t = tasks[i]
        if deadline and time.time() > deadline: return None
        if t['t0'] is None: t['t0'] = time.time()
        ev.wait_for_space([wine.build, tempfile.gettempdir(), edir], f'before {i}')
        bk = os.path.join(backups, f'{i}_{u}'); os.makedirs(bk, exist_ok=True)       # evaluate_record names its backup <id>.backup.json: one directory per code,
        t1 = time.time()                                                           # since several codes of the same task are judged at the same time
        r = slim(ev.evaluate_record(wine, t['rec'], t['codes'][u] + '\n', 'code', bdir, bk, a)); r['seconds'] = round(time.time() - t1, 1)
        try: os.rmdir(bk)
        except OSError: pass
        return r

    try:
        for (i, u), r in ev.run_parallel(trees, items, one):
            t = tasks[i]; t['res'][u] = r; t['left'] -= 1; judged += 1
            with open(os.path.join(pdir, i + '.jsonl'), 'a', encoding='utf-8') as pf: pf.write(json.dumps(dict(key=key(t['codes'][u]), result=r), ensure_ascii=False) + '\n')
            if t['left'] == 0:
                o = finish(i); written += 1; c = {}
                for x in o['statuses']: c[x] = c.get(x, 0) + 1
                print(f'[{a.model}] {done0 + written}/{n_tasks} {i} {o["module"]}!{o["function"]}: {o["passed"]}/{o["n"]} pass, {o["compiled"]} compiled, '
                      f'{o["distinct"]} distinct | {dict(sorted(c.items(), key=lambda kv: -kv[1]))}  ({o["seconds"]}s; {judged / max(1, time.time() - t_start) * 60:.0f} codes/min)', flush=True)
    except ev.Fatal as e:
        sys.exit(f'FATAL: {e}')
    print(f'[{a.model}] shard {a.shard}: {done0 + written}/{n_tasks} tasks evaluated; {judged} codes judged in {(time.time() - t_start) / 60:.0f} min', flush=True)

if __name__ == '__main__':
    main()
