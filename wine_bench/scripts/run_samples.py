#!/usr/bin/env python3
"""run_samples.py - N independent replies per task from one local model (for pass@k), asked for with the API's "n".

    python3 scripts/run_samples.py --scenario 1.1 --model qwen3.8-27b --n 100 --chunk 20 --workers 3

One request returns `chunk` replies to the same prompt (the server decodes them as one batch and computes the prompt
once); a task takes n / chunk requests, `workers` tasks are in flight at a time, so workers * chunk sequences are being
generated at any moment.  Nothing else differs from run_llm.py's sampled runs (<model>-s1): same prompts, same request
(no temperature field: the model's generation_config.json applies; max_tokens and the thinking switch of models.toml),
same format check - except that no seed is sent (a fixed seed would have to differ per reply).

Reads  runs/<scenario>/programmer/prompts/<id>.json
Writes runs/<scenario>/programmer/samples/<model>-n<N>/<id>.json : ONE file per task with all N replies
       {"id", "n", "samples": [{"response", "code" (None = no usable code), "finish"}, ...], "usage", ...}
Resumable: a task that has its file is skipped; a task is written only when all its N replies are there.
Exit status 1 if a task could not be completed (the job script then does not start the evaluation).
"""
import os, sys, json, glob, time, argparse, copy, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args
from bench.dataset import select_ids
from bench import llm, report

def ask(m, run, system, messages, k):
    """one request for k replies -> ([(text, finish_reason)] * k, usage); raises after the retries are used up"""
    body = dict(model=m['model'], messages=[{'role': 'system', 'content': system}] + messages, n=k)
    if m.get('send_temperature', True): body['temperature'] = run.get('temperature', 0.0)
    if run.get('max_tokens'): body[m.get('max_tokens_field', 'max_tokens')] = run['max_tokens']
    body.update(m.get('extra', {}))
    err = None
    for attempt in range(1, run.get('max_retries', 3) + 1):
        try:
            r = llm._post(m['base_url'].rstrip('/') + '/chat/completions', {'Authorization': f'Bearer {llm.api_key(m)}'}, body, run.get('timeout_s', 900))
            ch = r.get('choices') or []
            if len(ch) != k: raise ValueError(f'asked for n={k}, got {len(ch)} choices')
            return [((c.get('message') or {}).get('content') or '', c.get('finish_reason')) for c in ch], dict(r.get('usage') or {}, served_model=r.get('model'))
        except urllib.error.HTTPError as e:
            err = f'HTTP {e.code}: {e.read().decode(errors="ignore")[:300]}'
            if e.code in (400, 401, 403, 404): break
        except Exception as e: err = f'{type(e).__name__}: {e}'
        time.sleep(5 * attempt)
    raise RuntimeError(err)

def one_task(m, run, p, n, chunk, fmt, out_file, deadline):
    t0 = time.time(); samples = []; usage = dict(prompt_tokens=0, completion_tokens=0); served = None; requests = 0
    while len(samples) < n:
        if deadline and time.time() > deadline: return None                 # the job's time is nearly used up: not written, done next time
        k = min(chunk, n - len(samples))
        got, u = ask(m, run, p['system'], p['messages'], k); requests += 1
        for text, fin in got:
            c = report.check(text, fmt, p.get('c_name') or p['function'])
            samples.append(dict(response=text, code=c['parsed']['code'] if c['parsed'] else None, finish=fin))
        usage['prompt_tokens'] += u.get('prompt_tokens') or 0; usage['completion_tokens'] += u.get('completion_tokens') or 0
        served = u.get('served_model') or served
    rec = dict(id=p['id'], dll=p['dll'], function=p['function'], stage=p.get('stage'), model=m['name'], model_id=m['model'],
               served_model=served, provider=m['provider'], n=n, chunk=chunk, requests=requests,
               request=dict(max_tokens=run.get('max_tokens'), temperature='generation_config.json' if not m.get('send_temperature', True) else run.get('temperature'),
                            seed=None, extra=m.get('extra', {})),
               with_code=sum(1 for s in samples if s['code']), truncated=sum(1 for s in samples if s['finish'] == 'length'),
               distinct_code=len({s['code'] for s in samples if s['code']}), usage=usage, seconds=round(time.time() - t0, 1), samples=samples)
    tmp = out_file + '.tmp'; json.dump(rec, open(tmp, 'w'), ensure_ascii=False); os.replace(tmp, out_file)
    return rec

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--model', required=True, help='model name (folder under ~/scratch/models); the request settings of <model>-s1 in models.toml are used')
    ap.add_argument('--n', type=int, default=100, help='replies per task')
    ap.add_argument('--chunk', type=int, default=20, help='replies per request (the API\'s n)')
    ap.add_argument('--workers', type=int, default=4, help='tasks in flight; workers * chunk sequences are generated at once')
    ap.add_argument('--seconds', type=int, default=0, help='stop starting requests after this many seconds (the job\'s time budget)')
    ap.set_defaults(stage='programmer')
    a = ap.parse_args()
    if not a.scenario: ap.error('--scenario is required')
    scn = load_scenario(a.scenario); st = scn.stage(a.stage); stage_dir = scn.out(a.stage)
    pdir = os.path.join(stage_dir, 'prompts')
    ids = select_ids(a.ids, a.limit, [os.path.basename(f)[:4] for f in glob.glob(os.path.join(pdir, '[0-9]*.json'))])
    if not ids: sys.exit(f'no prompts in {pdir}')
    fmt = dict(kind=st.get('reply_format', 'json'), headings=st.get('required_headings', []))
    by_name = {m['name']: m for m in scn.models}
    base = by_name.get(a.model + '-s1') or by_name.get(a.model)
    if not base: sys.exit(f'{a.model}: not in models.toml')
    m = copy.deepcopy(base); m['name'] = f'{a.model}-n{a.n}'; m['send_temperature'] = False
    m['extra'] = {k: v for k, v in m.get('extra', {}).items() if k != 'seed'}
    if os.environ.get('WB_LOCAL_PORT'):
        import re
        m['base_url'] = re.sub(r':\d+/', ':' + os.environ['WB_LOCAL_PORT'] + '/', m['base_url'])
    if '127.0.0.1' not in m['base_url'] and 'localhost' not in m['base_url']: sys.exit(f'{a.model}: not a local model - this script is for the job\'s own vLLM server')
    run = llm.run_settings(scn.run, m)
    d = os.path.join(stage_dir, 'samples', m['name']); os.makedirs(d, exist_ok=True)
    todo = [i for i in ids if not os.path.exists(os.path.join(d, i + '.json'))]
    print(f'[{m["name"]}] {len(todo)} tasks to sample ({len(ids) - len(todo)} already done); n={a.n}, {a.chunk} replies per request, {a.workers} tasks at once '
          f'= {a.workers * a.chunk} sequences in flight; request: max_tokens={run.get("max_tokens")}, extra={m["extra"]}, no temperature, no seed', flush=True)
    deadline = time.time() + a.seconds if a.seconds else 0
    failed = skipped = 0; t0 = time.time(); toks = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {}
        for i in todo:
            p = json.load(open(os.path.join(pdir, i + '.json'), encoding='utf-8'))
            futs[ex.submit(one_task, m, run, p, a.n, a.chunk, fmt, os.path.join(d, i + '.json'), deadline)] = p
        for k, fu in enumerate(as_completed(futs), 1):
            p = futs[fu]
            try: r = fu.result()
            except Exception as e:
                failed += 1; print(f'[{m["name"]}] {k}/{len(todo)} {p["id"]} {p["dll"]}!{p["function"]}: ERR {str(e)[:200]}', flush=True); continue
            if r is None: skipped += 1; continue
            toks += r['usage']['completion_tokens']
            print(f'[{m["name"]}] {k}/{len(todo)} {p["id"]} {p["dll"]}!{p["function"]}: {r["with_code"]}/{r["n"]} with code, {r["distinct_code"]} distinct, '
                  f'{r["truncated"]} truncated, {r["seconds"]}s  ({toks / max(1, time.time() - t0):.0f} tok/s overall)', flush=True)
    done = sum(1 for i in ids if os.path.exists(os.path.join(d, i + '.json')))
    print(f'[{m["name"]}] {done}/{len(ids)} tasks have their {a.n} replies; {failed} failed, {skipped} not started (time budget)', flush=True)
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()
