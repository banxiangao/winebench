#!/usr/bin/env python3
"""metrics.py - cost of every task of every setting: time, tokens, agent iterations, next to its evaluation result.

    python3 vulcan/metrics.py [--root .] [--out results]          (run inside the container or any Python >= 3.8)

Reads (nothing is recomputed, these fields are written by the generation and evaluation jobs):
  wine_agent/runs/scenario<S>/<harness>/responses/<model>/<id>.json   seconds, usage, steps, exit_status, tool_counts, ...
  wine_agent/runs/scenario<S>/<harness>/eval/<model>/<id>.json        status
  wine_bench/runs/scenario<S>/programmer/responses/<model>/<id>.json  one reply per task (API models; harness "oneshot1")
  wine_bench/runs/scenario<S>/programmer/eval/<model>/<id>.json       its status
  wine_bench/runs/scenario<S>/programmer/samples/<model>-n<N>/<id>.json        n replies of one task: usage, seconds
  wine_bench/runs/scenario<S>/programmer/samples_eval/<model>-n<N>/<id>.json   passed, compiled of the n replies
Writes
  <out>/metrics_tasks.csv      one line per task and setting
  <out>/metrics_settings.csv   one line per setting: sums and means (and .txt, the same as an aligned table)

Columns that need explaining
  steps              agent: model calls of the task (= iterations of the agent loop); one-shot: empty
  compile_runs       agent: how often the task really ran ./compile (counted from the script's own output); compile_runs_ok: how many of
                     them succeeded; last_compile_ok: 1 if the last one did.  `compiles` is the runner's older count, which also takes
                     commands that only name ./compile or make - the limit of 5 failed compiles was applied to that count
  prompt_tokens      agent: summed over all model calls of the task (the history is re-sent at every step);
                     one-shot: tokens of the prompt (once; the server computes it once per request of `chunk` replies)
  completion_tokens  agent: summed over the task; one-shot: summed over the n replies (completion_tokens_per_reply = / n)
  seconds            agent: wall time of the task, with AGENT_WORKERS tasks running at once on the same server;
                     one-shot: wall time until all n replies of the task were there, generated in batches of `chunk`
                     with other tasks in flight - NOT the latency of a single request
  status             agent: evaluation result of the submission; one-shot: empty (see passed / compiled of n)
"""
import os, re, sys, json, glob, csv, argparse, statistics

def jload(f):
    try: return json.load(open(f, encoding='utf-8'))
    except Exception: return None

OK_RE = re.compile(r"^compiled OK: ", re.M); FAIL_RE = re.compile(r"^compile FAILED \(make exit status", re.M)
def compile_runs(traj_file, harness):
    """how often the agent really ran ./compile, and how often it succeeded -> (runs, successful, was the last one successful).
    Counted from the last line the script prints ("compiled OK: ..." / "compile FAILED (make exit status N)") in the outputs
    of the agent's commands, not from the text of the commands: the runner's own count (column `compiles`) also takes any
    command that merely names ./compile or make.  A run whose output the agent cut off (./compile | grep ...) is missed."""
    t = jload(traj_file)
    if not t: return "", "", ""
    texts = []
    if harness == "openhands":
        for e in t.get("events", []):
            o = e.get("observation")
            if isinstance(o, dict):
                c = o.get("content"); texts.append("\n".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c or ""))
    else:
        for m in t.get("messages", []):
            ex = m.get("extra") or {}
            if "returncode" in ex or m.get("role") == "tool": texts.append(str(ex.get("raw_output") if ex.get("raw_output") is not None else m.get("content") or ""))
    ok = bad = 0; last = ""
    for x in texts:                                     # in the order of the run
        marks = sorted([(m.start(), True) for m in OK_RE.finditer(x)] + [(m.start(), False) for m in FAIL_RE.finditer(x)])
        ok += sum(1 for _, good in marks if good); bad += sum(1 for _, good in marks if not good)
        if marks: last = int(marks[-1][1])
    return ok + bad, ok, last

def dataset_info(root):
    info = {}
    for d in glob.glob(os.path.join(root, 'wine_agent', 'dataset', 'winebench205_doc', '[0-9][0-9][0-9][0-9]_*.json')):
        r = jload(d)
        if not r: continue
        w = r.get('winebench') or {}
        info[r['id']] = dict(module=r['function']['module'], function=r['function']['export_name'], category=(w.get('category') or {}).get('l1', ''),
                             loc=(w.get('loc') or {}).get('total', ''), cyclomatic=w.get('cyclomatic', ''),
                             test_files=len(r['native_tests']['files']), doc_chars=sum(len(x.get('text') or '') for x in r.get('docs') or []))
    return info

COLS = ['scenario', 'harness', 'model', 'id', 'module', 'function', 'category', 'loc', 'cyclomatic', 'test_files', 'doc_chars',
        'seconds', 'prompt_tokens', 'completion_tokens', 'steps', 'commands', 'edits', 'compiles', 'compile_runs', 'compile_runs_ok', 'last_compile_ok', 'exit_status', 'tool_mode',
        'tool_name_fixes', 'tool_arg_fixes', 'status', 'identical', 'attempts', 'generation_failed',
        'n', 'requests', 'with_code', 'truncated', 'completion_tokens_per_reply', 'passed', 'compiled', 'eval_seconds']

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); ap.add_argument('--out', default='')
    a = ap.parse_args(); root = os.path.abspath(a.root); out = a.out or os.path.join(root, 'results'); os.makedirs(out, exist_ok=True)
    info = dataset_info(root); rows = []
    for d in sorted(glob.glob(os.path.join(root, 'wine_agent', 'runs', 'scenario*', '*', 'responses', '*'))):
        p = d.split(os.sep); scen, harness, model = p[-4][8:], p[-3], p[-1]
        for f in sorted(glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json'))):
            r = jload(f)
            if not r: continue
            e = jload(os.path.join(os.path.dirname(os.path.dirname(d)), 'eval', model, r['id'] + '.json')) or {}
            u = r.get('usage') or {}; tc = r.get('tool_counts') or {}
            cr, cr_ok, cr_last = compile_runs(f[:-5] + '.traj.json', harness)
            rows.append(dict(info.get(r['id'], {}), scenario=scen, harness=harness, model=model, id=r['id'], seconds=r.get('seconds'),
                             prompt_tokens=u.get('prompt_tokens'), completion_tokens=u.get('completion_tokens'), steps=r.get('steps'),
                             commands=tc.get('commands', ''), edits=tc.get('edits', ''), compiles=len(r.get('compiles') or []), compile_runs=cr, compile_runs_ok=cr_ok, last_compile_ok=cr_last,
                             exit_status=r.get('exit_status'), tool_mode=r.get('tool_mode'), tool_name_fixes=r.get('tool_name_fixes', ''),
                             tool_arg_fixes=r.get('tool_arg_fixes', ''), status=e.get('status', ''), identical=e.get('identical', ''),
                             attempts=r.get('gen_attempts_made', ''), generation_failed=r.get('generation_failed', '')))
    # one reply per task (the API models, vulcan/run_api.sbatch): harness "oneshot1"
    for d in sorted(glob.glob(os.path.join(root, 'wine_bench', 'runs', 'scenario*', 'programmer', 'responses', '*'))):
        p = d.split(os.sep); scen, model = p[-4][8:], p[-1]
        for f in sorted(glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json'))):
            r = jload(f)
            if not r: continue
            e = jload(os.path.join(os.path.dirname(os.path.dirname(d)), 'eval', model, r['id'] + '.json')) or {}
            u = r.get('usage') or {}
            rows.append(dict(info.get(r['id'], {}), scenario=scen, harness='oneshot1', model=model, id=r['id'], seconds=r.get('seconds'),
                             prompt_tokens=u.get('prompt_tokens'), completion_tokens=u.get('completion_tokens'), status=e.get('status', ''),
                             identical=e.get('identical', ''), attempts=r.get('attempts', 1), generation_failed=r.get('generation_failed', ''),
                             n=1, requests=r.get('attempts', 1), with_code=int(bool(r.get('format_ok'))), truncated=int(bool(r.get('truncated')))))
    for d in sorted(glob.glob(os.path.join(root, 'wine_bench', 'runs', 'scenario*', 'programmer', 'samples', '*'))):
        p = d.split(os.sep); scen, model = p[-4][8:], p[-1]
        for f in sorted(glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json'))):
            r = jload(f)
            if not r: continue
            e = jload(os.path.join(os.path.dirname(os.path.dirname(d)), 'samples_eval', model, r['id'] + '.json')) or {}
            u = r.get('usage') or {}; n = r.get('n') or 1; req = r.get('requests') or 1
            rows.append(dict(info.get(r['id'], {}), scenario=scen, harness='oneshot', model=model, id=r['id'], seconds=r.get('seconds'),
                             prompt_tokens=round((u.get('prompt_tokens') or 0) / req), completion_tokens=u.get('completion_tokens'),
                             n=n, requests=req, with_code=r.get('with_code'), truncated=r.get('truncated'),
                             completion_tokens_per_reply=round((u.get('completion_tokens') or 0) / n, 1),
                             passed=e.get('passed', ''), compiled=e.get('compiled', ''), eval_seconds=e.get('seconds', '')))
    with open(os.path.join(out, 'metrics_tasks.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, COLS, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

    def num(xs): return [x for x in xs if isinstance(x, (int, float))]
    def mean(xs): xs = num(xs); return round(statistics.mean(xs), 1) if xs else ''
    def med(xs): xs = num(xs); return round(statistics.median(xs), 1) if xs else ''
    def tot(xs): xs = num(xs); return round(sum(xs)) if xs else ''
    groups = {}
    for r in rows: groups.setdefault((r['scenario'], r['harness'], r['model']), []).append(r)
    srows = []
    for (scen, harness, model), g in sorted(groups.items()):
        s = dict(scenario=scen, harness=harness, model=model, tasks=len(g))
        if harness == 'oneshot':
            n = sum(r['n'] for r in g); ev = [r for r in g if r['passed'] != '']
            s.update(replies=n, evaluated_tasks=len(ev), passed_replies=tot(r['passed'] for r in ev), compiled_replies=tot(r['compiled'] for r in ev),
                     tasks_with_a_pass=sum(1 for r in ev if r['passed']))
        else:
            ev = [r for r in g if r['status']]
            s.update(evaluated_tasks=len(ev), passed=sum(1 for r in ev if r['status'] == 'pass'),
                     submitted=sum(1 for r in g if r.get('exit_status') == 'Submitted') if harness != 'oneshot1' else '',
                     steps_mean=mean(r.get('steps') for r in g), steps_median=med(r.get('steps') for r in g), steps_max=max(num(r.get('steps') for r in g) or [''])),
        s = s[0] if isinstance(s, tuple) else s
        if harness != 'oneshot':                                    # how the tasks ended (evaluation)
            for st in ('test_fail', 'crash', 'timeout', 'compile_fail', 'splice_fail', 'no_code'): s[st] = sum(1 for r in g if r.get('status') == st)
        if harness in ('mini_swe', 'openhands'):                     # the agent's own ./compile runs during the task
            runs = num(r.get('compile_runs') for r in g); oks = num(r.get('compile_runs_ok') for r in g)
            s.update(compile_runs_total=sum(runs), compile_runs_mean=round(sum(runs) / len(g), 2), compile_runs_ok_share=round(sum(oks) / sum(runs), 3) if sum(runs) else '',
                     tasks_without_compile_run=sum(1 for x in runs if x == 0), tasks_last_compile_ok=sum(1 for r in g if r.get('last_compile_ok') == 1))
        if any(r.get('generation_failed') not in ('', None) for r in g):          # settings run with the two-attempt rule (API models)
            s.update(second_attempts=sum(1 for r in g if isinstance(r.get('attempts'), int) and r['attempts'] > 1),
                     generation_failed=sum(1 for r in g if r.get('generation_failed') is True))
        s.update(seconds_total=tot(r['seconds'] for r in g), seconds_mean=mean(r['seconds'] for r in g), seconds_median=med(r['seconds'] for r in g),
                 prompt_tokens_total=tot(r['prompt_tokens'] for r in g), prompt_tokens_mean=mean(r['prompt_tokens'] for r in g),
                 completion_tokens_total=tot(r['completion_tokens'] for r in g), completion_tokens_mean=mean(r['completion_tokens'] for r in g))
        if harness == 'oneshot': s['completion_tokens_per_reply'] = round(s['completion_tokens_total'] / max(1, s['replies']), 1) if s['completion_tokens_total'] != '' else ''
        srows.append(s)
    cols = list(dict.fromkeys(c for s in srows for c in s))
    with open(os.path.join(out, 'metrics_settings.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(srows)
    wd = {c: max([len(c)] + [len(str(s.get(c, ''))) for s in srows]) for c in cols}
    with open(os.path.join(out, 'metrics_settings.txt'), 'w', encoding='utf-8') as f:
        f.write('  '.join(c.ljust(wd[c]) for c in cols) + '\n')
        for s in srows: f.write('  '.join(str(s.get(c, '')).ljust(wd[c]) for c in cols) + '\n')
    print(f'{len(rows)} task lines, {len(srows)} settings -> {out}/metrics_tasks.csv, metrics_settings.csv, metrics_settings.txt')

if __name__ == '__main__':
    main()
