#!/usr/bin/env python3
"""run_mini_swe.py - scenarios 3.x with mini-swe-agent (https://github.com/SWE-agent/mini-swe-agent) as the agent.

    python3 scripts/run_mini_swe.py --scenario 2.1 --models claude-haiku-5-5 --limit 5
    python3 scripts/run_mini_swe.py --scenario 2.2 --models claude-haiku-5-5,openai-gpt-6-luna,deepseek-v4-flash --limit 100 --workers 2
    python3 scripts/run_mini_swe.py --scenario 2.1 --models M --redo-bad

The agent is the unmodified DefaultAgent of mini-swe-agent (one bash command per step, LocalEnvironment); what is ours is
the environment it runs in: a restricted copy of the Wine tree (scripts/make_swe_trees.sh: no tests, no git history, the
target function replaced by a stub) with a ./compile script, and the prompts (templates/swe_*.txt, stage "mini_swe").
Worker i uses ~/wine-swe-w<i> + ~/wine-build-swe-w<i> (--src / --build set worker 0's pair; the others add -w<i>).
Output: runs/<scenario>/mini_swe/responses/<model>/<id>.{json,patch,traj.json}; the .patch is evaluated by evaluate.py
(--stage mini_swe), which splices it into the hidden file exactly as the agent saw it.
"""
import os, sys, json, glob, time, argparse, threading, queue, re, warnings
warnings.filterwarnings('ignore')
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args
from bench.dataset import load_records, select_ids
from bench import report, swe, csplice

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--models', required=True, help='comma-separated model names from models.toml')
    ap.add_argument('--src', default='~/wine-swe', help='worker 0 restricted source tree (scripts/make_swe_trees.sh)')
    ap.add_argument('--build', default='~/wine-build-swe', help='worker 0 build copy')
    ap.add_argument('--workers', type=int, default=1, help='records in parallel = number of tree pairs')
    ap.add_argument('--jobs', type=int, default=0, help='make -j per ./compile (default: CPUs / workers)')
    ap.add_argument('--redo-bad', action='store_true', help='re-run records that errored or submitted nothing')
    ap.add_argument('--sample', type=int, default=0); ap.add_argument('--seed', type=int, default=20261102)
    ap.add_argument('--shard', default='', help='i/n: only the tasks whose position in the task list is i modulo n (one runner per tree: vulcan/run_setting.sbatch)')
    ap.add_argument('--consume-dataset', action='store_true', help='delete the dataset records once they are loaded, so that the agent cannot read them '
                    '(they hold the original implementations).  Refused unless WB_DATASET_IS_COPY=1: the directory must be a throw-away copy')
    ap.add_argument('--gen-attempts', type=int, default=0, help='N > 0 (API models): a task whose run was cut short by an API / network / runner error '
                                                                'is run once more, at most N runs in total; still failing -> generation_failed (bench/swe.py: gen_failed)')
    a = ap.parse_args()
    if not a.scenario: ap.error('--scenario is required')
    if a.stage == 'architect': a.stage = 'mini_swe'
    scn = load_scenario(a.scenario); cfg = scn.cfg.get('swe', {}); secrets = scn.secrets()
    os.environ.setdefault('MSWEA_SILENT_STARTUP', '1'); os.environ.setdefault('MSWEA_COST_TRACKING', 'ignore_errors')
    swe.install_tool_name_fix()                                       # local servers only, see bench/swe.py
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models import get_model
    from minisweagent.exceptions import InterruptAgentFlow

    class CompileLimitAgent(DefaultAgent):
        """DefaultAgent + the bench's rule: after max_compile_failures failed compiles the run ends (exit_status CompileLimit)
        and whatever is in the tree is the submission"""
        def __init__(self, model, env, *, max_compile_failures=5, **kw):
            super().__init__(model, env, **kw); self.max_compile_failures = max_compile_failures; self.compile_failures = 0
        def execute_actions(self, message):
            actions = message.get('extra', {}).get('actions', [])
            outputs = [self.env.execute(a) for a in actions]                     # raises Submitted on the finish command
            msgs = self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))
            for act, o in zip(actions, outputs):
                if swe.compile_result(swe.as_text(act.get('command')), o.get('output', ''), o.get('returncode')) is False: self.compile_failures += 1
            if 0 < self.max_compile_failures <= self.compile_failures:
                raise InterruptAgentFlow({'role': 'exit', 'content': 'CompileLimit', 'extra': {'exit_status': 'CompileLimit', 'submission': ''}})
            return msgs

    jobs = a.jobs or max(2, (os.cpu_count() or 2) // a.workers)
    trees = []
    for i in range(a.workers):
        sfx = f'-w{i}' if i else ''
        trees.append(swe.SweTree(os.path.expanduser(a.src) + sfx, os.path.expanduser(a.build) + sfx, jobs, f'w{i}'))
    stage_dir = scn.out(a.stage); pdir = os.path.join(stage_dir, 'prompts')
    prompts = {os.path.basename(f)[:4]: json.load(open(f, encoding='utf-8')) for f in glob.glob(os.path.join(pdir, '[0-9]*.json'))}
    if not prompts: sys.exit(f'no prompts in {pdir}: run  python3 scripts/build_prompts.py --scenario {a.scenario} --stage {a.stage}')
    ids = select_ids(a.ids, a.limit, prompts.keys())
    if a.sample: import random; ids = sorted(random.Random(a.seed).sample(ids, min(a.sample, len(ids))))
    if a.shard:
        si, sn = (int(x) for x in a.shard.split('/')); ids = [x for k, x in enumerate(ids) if k % sn == si]
    records = {r['id']: r for r in load_records(scn.dataset)}
    if a.consume_dataset:
        if os.environ.get('WB_DATASET_IS_COPY') != '1': sys.exit('--consume-dataset: WB_DATASET_IS_COPY=1 is not set - refusing to delete ' + scn.dataset)
        import shutil
        for x in os.listdir(scn.dataset): shutil.rmtree(os.path.join(scn.dataset, x), ignore_errors=True) if os.path.isdir(os.path.join(scn.dataset, x)) else os.remove(os.path.join(scn.dataset, x))
        print(f'dataset copy consumed: {len(records)} records in memory, {scn.dataset} emptied', flush=True)
    models = {m['name']: m for m in scn.models}
    free = queue.Queue(); [free.put(t) for t in trees]

    for name in a.models.split(','):
        m = models.get(name)
        if not m: sys.exit(f'{name}: not in models.toml')
        if not swe.key_env(m, secrets): sys.exit(f'{name}: no key ({m["api_key_env"]})')
        lname = swe.litellm_name(m); mkw = swe.litellm_kwargs(m)
        out_dir = os.path.join(stage_dir, 'responses', name); os.makedirs(out_dir, exist_ok=True)
        tmode = swe.tool_mode(cfg, m)
        def pending(i):
            f = os.path.join(out_dir, i + '.json')
            if not os.path.exists(f): return True
            r = json.load(open(f))
            return (a.redo_bad and report.is_bad(r)) or swe.stale(r, tmode)
        todo = [i for i in ids if pending(i)]
        print(f'[{name}] tool mode {tmode}; {len(todo)} to run ({len(ids) - len(todo)} already done); litellm model {lname} {mkw}', flush=True)

        def work(i):
            t0 = time.time(); rec = records[i]; p = prompts[i]; tree = free.get()
            try:
                try: info = tree.setup(rec)
                except csplice.SpliceError as e:                       # the record does not match this tree (e.g. 0157): record it, go on
                    out = dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname,
                               served_model=None, provider='litellm', agent=AGENT_NAME, response='', parsed=None, format_ok=False, code_leak=None,
                               truncated=False, exit_status='DatasetMismatch', steps=0, tool_counts={}, compiles=[], compiled_ok_last=False,
                               files=[], hidden=None, violations=[], usage=dict(prompt_tokens=0, completion_tokens=0), cost=0.0,
                               seconds=round(time.time() - t0, 1), error=str(e))
                    swe.write_result(out_dir, i, out, dict(id=i, model=name, error=str(e)), ''); return out
                mode = swe.tool_mode(cfg, m)
                mcfg = {'model_kwargs': {'drop_params': True, **mkw}, 'cost_tracking': 'ignore_errors'}
                if mode == 'text': mcfg['model_class'] = 'litellm_textbased'     # the command is a ```mswea_bash_command block in the reply
                model = get_model(lname, mcfg)
                env = LocalEnvironment(cwd=tree.src, timeout=cfg.get('command_timeout', 900),
                                       env={'PAGER': 'cat', 'MANPAGER': 'cat', 'LESS': '-R', 'GIT_PAGER': 'cat', **swe.offline_env()})
                agent = CompileLimitAgent(model, env, system_template=p['system'], instance_template=INSTANCE_TEMPLATE + (TEXT_FORMAT if mode == 'text' else ''),
                                     max_compile_failures=cfg.get('max_compile_failures', 5),
                                     step_limit=cfg.get('max_steps', 40), cost_limit=cfg.get('cost_limit', 0.0),
                                     wall_time_limit_seconds=cfg.get('wall_time_limit_seconds', 1800),
                                     max_consecutive_format_errors=cfg.get('max_format_errors', 3))
                error = None; swe.tool_fixes_take(); swe.tool_arg_fixes_take()
                try: result = agent.run(p['messages'][-1]['content'], max_compile_failures=cfg.get('max_compile_failures', 5))
                except Exception as e: result = {'exit_status': type(e).__name__, 'submission': ''}; error = str(e)[:500]
                patch = tree.patch()
                traj = agent.serialize()
                try: return finish(i, p, rec, tree, info, agent, result, error, patch, traj, t0)
                except Exception as e:
                    out = dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname, served_model=lname,
                               provider='litellm', agent=AGENT_NAME, response=patch, parsed={'patch': patch} if patch else None, format_ok=tree.target_changed(patch),
                               code_leak=None, truncated=False, exit_status=result.get('exit_status', ''), steps=agent.n_calls, tool_counts={}, compiles=[],
                               compiled_ok_last=False, files=tree.files_in(patch), hidden=info, violations=[], usage=dict(prompt_tokens=0, completion_tokens=0),
                               cost=round(agent.cost, 4), seconds=round(time.time() - t0, 1), error=f'runner: {type(e).__name__}: {e}'[:500])
                    swe.write_result(out_dir, i, out, traj, patch if out['format_ok'] else ''); return out
            finally:
                try: tree.reset()
                except Exception: pass
                free.put(tree)

        def finish(i, p, rec, tree, info, agent, result, error, patch, traj, t0):
            if True:
                calls, pending = [], []                            # pair each action with the observation that follows it
                for msg in traj['messages']:
                    if msg.get('role') == 'assistant': pending = [swe.as_text(x.get('command')) for x in msg.get('extra', {}).get('actions', [])]
                    elif msg.get('role') in ('user', 'tool') and pending and 'returncode' in (msg.get('extra') or {}):
                        ex = msg['extra']; calls.append((pending.pop(0), ex.get('raw_output') or '', ex.get('returncode', -1)))
                commands = [c for c, _, _ in calls]
                compiles = swe.compiles_from(calls)
                usage = dict(prompt_tokens=0, completion_tokens=0)
                for msg in traj['messages']:
                    u = ((msg.get('extra') or {}).get('response') or {}).get('usage') or {}
                    usage['prompt_tokens'] += u.get('prompt_tokens') or 0; usage['completion_tokens'] += u.get('completion_tokens') or 0
                has_code = tree.target_changed(patch)
                out = dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname,
                           served_model=lname, provider='litellm', agent='mini-swe-agent', agent_version=traj['info'].get('mini_version'),
                           tool_mode=swe.tool_mode(cfg, m),
                           response=patch if has_code else '', parsed={'patch': patch} if has_code else None, format_ok=has_code,
                           code_leak=None, truncated=False, exit_status=result.get('exit_status', ''), steps=agent.n_calls,
                           tool_counts={'commands': len(commands)}, compiles=compiles, compiled_ok_last=bool(compiles) and compiles[-1]['ok'],
                           files=tree.files_in(patch), hidden=info, violations=tree.violations(commands), usage=usage,
                           cost=round(agent.cost, 4), seconds=round(time.time() - t0, 1), error=error)
                out['tool_name_fixes'] = swe.tool_fixes_take(); out['tool_arg_fixes'] = swe.tool_arg_fixes_take()
                out['job'] = os.environ.get('WB_JOB_ID') or os.environ.get('SLURM_JOB_ID')   # which job produced this result (vulcan/run_setting.sbatch)
                out['agent_network'] = swe.agent_network()                              # what the agent's shell could reach (bench/swe.py)
                swe.write_result(out_dir, i, out, traj, patch if has_code else '')
                return out

        def safe_work(i):
            try: return work(i)
            except BaseException as e:                                # nothing is stored: the record is tried again by the next run
                p = prompts[i]
                return dict(id=i, dll=p['dll'], function=p['function'], format_ok=False, exit_status='RunnerError', steps=0, tool_counts={}, compiles=[],
                            compiled_ok_last=False, usage=dict(prompt_tokens=0, completion_tokens=0), seconds=0, error=f'{type(e).__name__}: {e}'[:300])
        def stub(i, error):                                           # --gen-attempts: a task whose runner crashed is stored like this
            p = prompts[i]
            return dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname, served_model=None,
                        provider='litellm', agent=AGENT_NAME, tool_mode=tmode, response='', parsed=None, format_ok=False, code_leak=None, truncated=False,
                        exit_status='RunnerError', steps=0, tool_counts={}, compiles=[], compiled_ok_last=False, files=[], hidden=None, violations=[],
                        usage=dict(prompt_tokens=0, completion_tokens=0), cost=0.0, seconds=0, error=error)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            if a.gen_attempts > 0: futs = [ex.submit(swe.run_capped, work, i, a.gen_attempts, out_dir, stub) for i in todo]
            else: futs = [ex.submit(safe_work, i) for i in todo]
            for k, fut in enumerate(as_completed(futs), 1): print(swe.status_line(name, k, len(todo), fut.result()), flush=True)
        if swe.TOOL_NAME_FIXES[0]: print(f'[{name}] tool-call names repaired so far (the server glued "json" to them): {swe.TOOL_NAME_FIXES[0]}', flush=True)
        print(f'[{name}] summary: {report.summarize(out_dir)}', flush=True)

AGENT_NAME = 'mini-swe-agent'

TEXT_FORMAT = """
## Response format

Every response must contain a short reasoning followed by EXACTLY ONE command in a code block of this exact form:

```mswea_bash_command
your_command_here
```

Nothing is executed unless it is inside such a block; one block per response.
"""

INSTANCE_TEMPLATE = """{{task}}

## How to work here

You are in the root of the source tree. Every command runs in a fresh subshell there (directory changes and variables do
not persist; prefix a command with `cd dir && ...` if needed). Use non-interactive commands only (no editors like vi;
edit files with sed, python, or `cat <<'EOF' > file`). Keep command output short (head, sed -n 'A,Bp', grep -n).

Recommended steps:
1. Find the stub and read the surrounding file, headers and similar functions.
2. Replace the stub body with your implementation (keep the prototype line as it is; add static helpers above it if useful).
3. Run ./compile and fix every error it reports. You have at most {{max_compile_failures}} failed compiles: after the
   {{max_compile_failures}}th failure the task ends and your current code is taken as it is, so read the errors carefully.
4. Re-read your code once for Windows semantics (error codes, output parameters, edge cases).
5. Finish by running exactly this command, on its own: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
   Your changes are collected from the modified files; after this command you cannot continue.

<system_information>
{{system}} {{release}} {{machine}}
</system_information>
"""

if __name__ == '__main__':
    main()
