#!/usr/bin/env python3
"""run_agent.py - scenarios 3.x: the benchmark's own agent (bench/agent.py) implements each function; the reply is C code.

    python3 scripts/run_agent.py --scenario 2.1 --src ~/wine --build ~/wine-build --models claude-haiku-5-5 --limit 5
    python3 scripts/run_agent.py --scenario 2.2 --src ~/wine --build ~/wine-build --models deepseek-v4-flash,openai-gpt-6-luna --workers 3
    python3 scripts/run_agent.py --scenario 2.1 --src ~/wine --models M              # no --build: the compile tool is unavailable
    python3 scripts/run_agent.py --scenario 2.1 --src ~/wine --build ~/wine-build --models M --redo-bad
    python3 scripts/run_agent.py --scenario 2.1 --src ~/wine --build ~/wine-build --models M --sample 50   # a fixed random subset of 50

The agent reads the Wine source tree at --src directly (tests and the original implementation are not served to it, see
bench/agent.py); compiling touches the tree under a lock and restores it, so --build must be a configured, fully built
tree of the same source (the one evaluate.py uses is fine).  Prompts: build_prompts.py --scenario 2.1 --stage agent.
Output: runs/<scenario>/agent/responses/<model>/<id>.json (same fields as run_llm.py + steps, tool_counts, compiles,
exit_status), <id>.c (the submission, evaluated like any programmer reply) and <id>.traj.json (the trajectory).
"""
import os, sys, json, glob, time, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args
from bench.dataset import load_records, select_ids
from bench import llm, report, csplice
from bench.agent import Workspace, run_agent

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--models', required=True, help='comma-separated model names from models.toml')
    ap.add_argument('--src', required=True, help='Wine source tree (read by the agent; touched only while compiling)')
    ap.add_argument('--build', default='', help='configured + built Wine build dir; without it the compile tool is unavailable')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 2, help='make -j for the compile tool')
    ap.add_argument('--workers', type=int, default=0, help='parallel records (compiles are serialized); default [run].workers')
    ap.add_argument('--redo-bad', action='store_true', help='re-run records that errored or submitted nothing')
    ap.add_argument('--sample', type=int, default=0, help='a random subset of N records (deterministic with --seed; use the same N and seed for every model)')
    ap.add_argument('--seed', type=int, default=20261102)
    a = ap.parse_args()
    if not a.scenario: ap.error('--scenario is required')
    scn = load_scenario(a.scenario); cfg = scn.cfg.get('agent', {}); llm.SECRETS = scn.secrets()
    if a.stage == 'architect': a.stage = 'agent'
    a.src = os.path.abspath(os.path.expanduser(a.src))
    if not os.path.isdir(os.path.join(a.src, 'dlls')): sys.exit(f'--src {a.src}: not a Wine source tree')
    wine = None
    if a.build:
        from evaluate import Wine
        wine = Wine(a.src, os.path.expanduser(a.build), a.jobs, cfg.get('compile_timeout', 900), 60, '')
    elif 'compile' in cfg.get('tools', ['compile']): print('note: no --build given, the compile tool will answer "not available"')
    stage_dir = scn.out(a.stage); pdir = os.path.join(stage_dir, 'prompts')
    prompts = {os.path.basename(f)[:4]: json.load(open(f, encoding='utf-8')) for f in glob.glob(os.path.join(pdir, '[0-9]*.json'))}
    if not prompts: sys.exit(f'no prompts in {pdir}: run build_prompts.py --scenario {a.scenario} --stage agent first')
    ids = select_ids(a.ids, a.limit, prompts.keys())
    if a.sample: import random; ids = sorted(random.Random(a.seed).sample(ids, min(a.sample, len(ids))))
    records = {r['id']: r for r in load_records(scn.dataset)}
    models = {m['name']: m for m in scn.models}
    lock = threading.Lock()
    for name in a.models.split(','):
        m = models.get(name)
        if not m: sys.exit(f'{name}: not in models.toml')
        if not llm.api_key(m): sys.exit(f'{name}: no key ({m["api_key_env"]})')
        run = llm.run_settings(scn.run, m); out_dir = os.path.join(stage_dir, 'responses', name); os.makedirs(out_dir, exist_ok=True)
        todo = []
        for i in ids:
            f = os.path.join(out_dir, i + '.json')
            if os.path.exists(f) and not (a.redo_bad and report.is_bad(json.load(open(f)))): continue
            todo.append(i)
        print(f'[{name}] {len(todo)} to run ({len(ids) - len(todo)} already done)', flush=True)

        def work(i):
            t0 = time.time(); rec = records[i]; p = prompts[i]
            try: ws = Workspace(a.src, rec, cfg, wine, lock)
            except csplice.SpliceError as e:                 # the record does not match this source tree: record it, go on
                r = dict(code=None, served_model=None, exit_status='DatasetMismatch', steps=0, tool_counts={}, compiles=[], denied=[],
                         hidden=None, code_written=False, usage=dict(prompt_tokens=0, completion_tokens=0), history=[], error=str(e))
            else: r = run_agent(m, run, p['system'], p['messages'][-1]['content'], ws, cfg)
            code = r['code']
            out = dict(id=i, dll=p['dll'], function=p['function'], stage='agent', from_model=None, model=name, model_id=m['model'],
                       served_model=r['served_model'], provider=m['provider'], response=code or '',
                       parsed={'code': code} if code else None, format_ok=code is not None, code_leak=None, truncated=False,
                       exit_status=r['exit_status'], steps=r['steps'], tool_counts=r['tool_counts'], compiles=r['compiles'],
                       compiled_ok_last=bool(r['compiles']) and r['compiles'][-1]['ok'], denied=r['denied'], hidden=r['hidden'],
                       code_written=r['code_written'], usage=r['usage'], seconds=round(time.time() - t0, 1), error=r['error'])
            f = os.path.join(out_dir, i + '.json')
            if os.path.exists(f):
                old = json.load(open(f)); out['attempts'] = old.get('attempts', 1) + 1
                os.replace(f, f[:-5] + f'.attempt{out["attempts"] - 1}.json')
            json.dump(out, open(f + '.tmp', 'w'), indent=1, ensure_ascii=False); os.replace(f + '.tmp', f)
            json.dump(dict(id=i, model=name, exit_status=r['exit_status'], history=r['history']), open(os.path.join(out_dir, i + '.traj.json'), 'w'), indent=1, ensure_ascii=False)
            cf = os.path.join(out_dir, i + '.c')
            if code: open(cf, 'w').write(code + '\n')
            elif os.path.exists(cf): os.remove(cf)
            return out

        workers = a.workers or scn.run.get('workers', 1)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, i) for i in todo]
            for k, fut in enumerate(as_completed(futs), 1):
                r = fut.result(); tc = r['tool_counts']
                print(f'[{name}] {k}/{len(todo)} {r["id"]} {r["dll"]}!{r["function"]}: {"ok" if r["format_ok"] else "no-code"} '
                      f'exit={r["exit_status"]} steps={r["steps"]} reads={tc.get("read_file", 0)} searches={tc.get("search", 0)} '
                      f'compiles={len(r["compiles"])}{"(ok)" if r["compiled_ok_last"] else ""} tokens={r["usage"]["prompt_tokens"]}+{r["usage"]["completion_tokens"]} '
                      f'{r["seconds"]}s' + (f'  ERR {r["error"][:80]}' if r['error'] else ''), flush=True)
        print(f'[{name}] summary: {report.summarize(out_dir)}')

if __name__ == '__main__':
    main()
