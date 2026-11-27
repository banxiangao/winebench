#!/usr/bin/env python3
"""run_openhands.py - scenarios 3.x with OpenHands (the OpenHands agent SDK, https://github.com/OpenHands/software-agent-sdk)
as the agent.

    python3 scripts/run_openhands.py --scenario 2.1 --models claude-haiku-5-5 --limit 5
    python3 scripts/run_openhands.py --scenario 2.2 --models claude-haiku-5-5,openai-gpt-6-luna,deepseek-v4-flash --limit 100 --workers 2
    python3 scripts/run_openhands.py --scenario 2.1 --models M --redo-bad

The agent is OpenHands' standard Agent with its terminal and file-editor tools (no browser, no task tracker) on a local
workspace; what is ours is the workspace: a restricted copy of the Wine tree (scripts/make_swe_trees.sh: no tests, no
git history, the target function replaced by a stub) with a ./compile script, and the task text (templates/swe_*.txt,
stage "openhands" - the system part of the prompt is sent as the first part of the task message, OpenHands keeps its own
system prompt).  Worker i uses ~/wine-swe-w<i> + ~/wine-build-swe-w<i>.
Output: runs/<scenario>/openhands/responses/<model>/<id>.{json,patch,traj.json}; evaluate with evaluate.py --stage openhands.
"""
import os, sys, json, glob, time, argparse, queue, logging, warnings
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
    if a.stage == 'architect': a.stage = 'openhands'
    scn = load_scenario(a.scenario); cfg = scn.cfg.get('swe', {}); secrets = scn.secrets()
    os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER', '1'); os.environ.setdefault('LOG_LEVEL', 'ERROR')
    swe.install_tool_name_fix()                                       # local servers only, see bench/swe.py
    from openhands.sdk import LLM, Agent, Conversation, Tool
    from openhands.sdk.conversation.state import ConversationExecutionStatus
    from openhands.sdk.event.llm_convertible import ActionEvent, ObservationEvent, MessageEvent
    from openhands.tools.terminal import TerminalTool
    from openhands.tools.file_editor import FileEditorTool
    logging.getLogger('openhands').setLevel(logging.ERROR)
    from openhands.tools.terminal.impl import TerminalExecutor
    swe.install_tool_name_fix()                                       # again: the SDK bound litellm's function when it was imported
    cap = float(cfg.get('command_timeout', 900)); _orig_call = TerminalExecutor.__call__
    def _capped_call(self, action, conversation=None):
        """the model may ask for any timeout (seen: 10000 s on a command with an unclosed quote, which then hung for 2.8 h):
        every command gets a hard limit of [swe].command_timeout; the next command interrupts a timed-out one"""
        if not action.is_input and (action.timeout is None or action.timeout > cap): action = action.model_copy(update={'timeout': cap})
        return _orig_call(self, action, conversation)
    TerminalExecutor.__call__ = _capped_call

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
        key = swe.key_env(m, secrets)
        if not key: sys.exit(f'{name}: no key ({m["api_key_env"]})')
        lname = swe.litellm_name(m); mkw = swe.litellm_kwargs(m)
        mode = swe.tool_mode(cfg, m)                                       # text = OpenHands' prompt-based function calling
        llm_fields = dict(model=lname, api_key=key, usage_id='agent', drop_params=True, native_tool_calling=(mode == 'native'))
        if 'api_base' in mkw: llm_fields['base_url'] = mkw['api_base']
        if 'temperature' in mkw: llm_fields['temperature'] = mkw['temperature']
        if 'reasoning_effort' in mkw: llm_fields['reasoning_effort'] = mkw['reasoning_effort']
        elif swe.is_local(m): llm_fields['reasoning_effort'] = None     # local server: nothing sent (the model's `extra` goes into the body)
        else: llm_fields['reasoning_effort'] = 'none'                   # the bench runs every model without reasoning
        for k in ('max_tokens', 'max_completion_tokens'):
            if k in mkw: llm_fields['max_output_tokens'] = mkw[k]
        if mkw.get('extra_body'): llm_fields['litellm_extra_body'] = mkw['extra_body']
        out_dir = os.path.join(stage_dir, 'responses', name); os.makedirs(out_dir, exist_ok=True)
        tmode = swe.tool_mode(cfg, m)
        def pending(i):
            f = os.path.join(out_dir, i + '.json')
            if not os.path.exists(f): return True
            r = json.load(open(f))
            return (a.redo_bad and report.is_bad(r)) or swe.stale(r, tmode)
        todo = [i for i in ids if pending(i)]
        print(f'[{name}] tool mode {tmode}; {len(todo)} to run ({len(ids) - len(todo)} already done); litellm model {lname}', flush=True)

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
                llm = LLM(**{k: v for k, v in llm_fields.items() if k != 'litellm_extra_body' or v})
                tparams = {'no_change_timeout_seconds': cfg.get('command_timeout', 900)}
                if swe.offline_env(): tparams['env'] = swe.offline_env()       # API runs: the job's proxy is not for the agent's terminal
                agent = Agent(llm=llm, tools=[Tool(name=TerminalTool.name, params=tparams),
                                              Tool(name=FileEditorTool.name)],
                              system_prompt_kwargs={'cli_mode': True})
                error = None; status = ''; swe.tool_fixes_take(); swe.tool_arg_fixes_take()
                import threading
                limit = cfg.get('max_compile_failures', 5); stop = threading.Event(); why = {}
                failures = [0]
                def on_event(e):                                        # count failed compiles; the watcher thread pauses the run
                    if isinstance(e, ObservationEvent) and e.tool_name == 'terminal':
                        obs = e.observation.model_dump(); cmd = obs.get('command') or ''
                        text = ' '.join(c.get('text', '') for c in obs.get('content', []) if isinstance(c, dict))
                        if swe.compile_result(cmd, text, obs.get('exit_code')) is False:
                            failures[0] += 1
                            if 0 < limit <= failures[0] and not why: why['reason'] = 'CompileLimit'; tree.stop_compiling(); stop.set()
                conv = Conversation(agent=agent, workspace=tree.src, persistence_dir=None, visualizer=None, callbacks=[on_event],
                                    max_iteration_per_run=cfg.get('max_steps', 40), stuck_detection=True,
                                    max_budget_per_run=cfg.get('cost_limit') or None)
                def watcher():                                           # wall-time limit or compile limit -> pause (from another thread, as documented)
                    if not stop.wait(cfg.get('wall_time_limit_seconds', 1800)): why.setdefault('reason', 'TimeExceeded')
                    if why.get('reason') in ('CompileLimit', 'TimeExceeded'): conv.pause()
                task = p['system'] + '\n\n---\n\n' + p['messages'][-1]['content'] + '\n\n' + TASK_FOOTER.replace('{N}', str(limit))
                try:
                    conv.send_message(task)
                    th = threading.Thread(target=watcher, daemon=True); th.start()
                    conv.run()
                    status = conv.state.execution_status.value
                    if status == ConversationExecutionStatus.PAUSED.value: status = why.get('reason', 'TimeExceeded')
                except Exception as e: status = type(e).__name__; error = str(e)[:500]
                finally:
                    if not why: why['reason'] = 'done'
                    stop.set()
                events = list(conv.state.events)
                try: traj = dict(id=i, model=name, agent='openhands-sdk', events=[e.model_dump(mode='json') for e in events])
                except Exception as e: traj = dict(id=i, model=name, agent='openhands-sdk', events=[], error=f'serialize: {e}')
                patch = tree.patch(); has_code = tree.target_changed(patch)
                try: out = summarize_run(i, p, tree, info, conv, events, status, error, patch, has_code, t0)
                except Exception as e:                                   # a parsing surprise must not kill the batch
                    out = dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname, served_model=lname,
                               provider='litellm', agent=AGENT_NAME, response=patch if has_code else '', parsed={'patch': patch} if has_code else None,
                               format_ok=has_code, code_leak=None, truncated=False, exit_status=status, steps=0, tool_counts={}, compiles=[],
                               compiled_ok_last=False, files=tree.files_in(patch), hidden=info, violations=[], usage=dict(prompt_tokens=0, completion_tokens=0),
                               cost=0.0, seconds=round(time.time() - t0, 1), error=f'runner: {type(e).__name__}: {e}'[:500])
                try: conv.close()
                except Exception: pass
                swe.write_result(out_dir, i, out, traj, patch if has_code else '')
                return out
            finally:
                try: tree.reset()
                except Exception: pass
                free.put(tree)

        def summarize_run(i, p, tree, info, conv, events, status, error, patch, has_code, t0):
            if True:
                calls, pending = [], {}
                for e in events:
                    if isinstance(e, ActionEvent):
                        act = e.action.model_dump() if e.action is not None else {}
                        pending[e.id] = (e.tool_name, act)                 # an observation points back at the action event's id
                    elif isinstance(e, ObservationEvent) and e.action_id in pending:
                        tool, act = pending.pop(e.action_id); obs = e.observation.model_dump()
                        text = ' '.join(c.get('text', '') for c in obs.get('content', []) if isinstance(c, dict)) if isinstance(obs.get('content'), list) else str(obs.get('content', ''))
                        if tool == 'terminal' or ('command' in act and 'path' not in act and 'message' not in act):
                            calls.append((swe.as_text(act.get('command')), text, obs.get('exit_code', -1)))
                        elif tool != 'finish':                                                    # file_editor and friends
                            calls.append((f'[{tool}] ' + json.dumps({k: v for k, v in act.items() if k in ('command', 'path', 'old_str', 'new_str')})[:300], text, 0))
                commands = [c for c, _, _ in calls if not c.startswith('[')]
                edits = [c for c, _, _ in calls if c.startswith('[')]
                metrics = conv.conversation_stats.get_combined_metrics()
                tu = metrics.accumulated_token_usage
                usage = dict(prompt_tokens=tu.prompt_tokens if tu else 0, completion_tokens=tu.completion_tokens if tu else 0)
                steps = sum(1 for e in events if isinstance(e, ActionEvent))
                exit_status = {'finished': 'Submitted', 'stuck': 'Stuck', 'error': 'ModelError', 'idle': 'LimitsExceeded'}.get(status, status)
                if status == 'error' and any(getattr(e, 'code', None) == 'MaxIterationsReached' for e in events):
                    exit_status = 'LimitsExceeded'                    # the step limit ends the conversation in state "error": not a model failure
                out = dict(id=i, dll=p['dll'], function=p['function'], stage=a.stage, from_model=None, model=name, model_id=lname,
                           served_model=lname, provider='litellm', agent='openhands-sdk', agent_version=openhands_version(), tool_mode=mode,
                           response=patch if has_code else '', parsed={'patch': patch} if has_code else None, format_ok=has_code,
                           code_leak=None, truncated=False, exit_status=exit_status, steps=steps,
                           tool_counts={'commands': len(commands), 'edits': len(edits)}, compiles=swe.compiles_from([c for c in calls if not c[0].startswith('[')]),
                           files=tree.files_in(patch), hidden=info, violations=tree.violations(commands + edits), usage=usage,
                           cost=round(metrics.accumulated_cost or 0.0, 4), seconds=round(time.time() - t0, 1), error=error)
                out['compiled_ok_last'] = bool(out['compiles']) and out['compiles'][-1]['ok']
                if status == 'error':                                 # what ended the conversation (used by swe.gen_failed)
                    out['error_detail'] = next((f'{getattr(e, "code", "")}: {getattr(e, "detail", "")}'[:500] for e in reversed(events)
                                                if getattr(e, 'code', None) and hasattr(e, 'detail')), None)
                out['tool_name_fixes'] = swe.tool_fixes_take(); out['tool_arg_fixes'] = swe.tool_arg_fixes_take()
                out['job'] = os.environ.get('WB_JOB_ID') or os.environ.get('SLURM_JOB_ID')   # which job produced this result (vulcan/run_setting.sbatch)
                out['agent_network'] = swe.agent_network()                              # what the agent's shell could reach (bench/swe.py)
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

def openhands_version():
    try:
        from importlib.metadata import version; return version('openhands-sdk')
    except Exception: return None

AGENT_NAME = 'openhands-sdk'

TASK_FOOTER = """How to work here: you are in the root of the source tree. Find the stub, read the surrounding file, headers and
similar functions; replace the stub body with your implementation (keep the prototype line; add static helpers above it if
useful); run ./compile and fix every error it reports. You have at most {N} failed compiles: after the {N}th failure the
task ends and your current code is taken as it is, so read the errors carefully. Re-read your code once for Windows
semantics (error codes, output parameters, edge cases). When it compiles and you are satisfied, call the finish tool. Your changes are collected from the
modified files; do not use git. Do not ask questions: nobody will answer; decide yourself and finish."""

if __name__ == '__main__':
    main()
