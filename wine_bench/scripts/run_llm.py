#!/usr/bin/env python3
"""run_llm.py - send the prompts of one stage of a scenario to the models and store the replies.

    python3 scripts/run_llm.py --scenario 1.1 --stage programmer --models deepseek-v4-flash --limit 10     # trial
    python3 scripts/run_llm.py --scenario 1.2 --stage programmer --redo-bad             # all enabled models, all prompts
    python3 scripts/run_llm.py --scenario 1.2 --stage programmer --models M --gen-attempts 2   # at most two requests per task
    (--from-model is for a stage that consumes another stage's replies; the current scenarios have only "programmer")

Reads  runs/<scenario>/<stage>[/from_<model>]/prompts/<id>.json   (made by build_prompts.py)
Writes runs/<scenario>/<stage>[/from_<model>]/responses/<model>/<id>.json and summary.json
       (+ <id>.c when the stage's reply_format is "code")
Resumable: existing replies are skipped; --redo-bad re-queries errors, truncated and badly formatted ones.
"""
import os, sys, json, glob, time, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args
from bench.dataset import select_ids
from bench import llm, report

def query(m, run, p, out_file, fmt):
    t0 = time.time()
    attempts = 1
    if os.path.exists(out_file):                                     # a retry: keep the earlier reply as <id>.attemptN.json
        old = json.load(open(out_file, encoding='utf-8')); attempts = old.get('attempts', 1) + 1
        os.replace(out_file, out_file[:-5] + f'.attempt{attempts - 1}.json')
    text, usage, truncated, err = llm.complete(m, run, p['system'], p['messages'])
    rec = dict(id=p['id'], dll=p['dll'], function=p['function'], stage=p.get('stage'), from_model=p.get('from_model'),
               model=m['name'], model_id=m['model'], served_model=usage.get('served_model'), provider=m['provider'], response=text, **report.check(text, fmt, p.get('c_name') or p['function']), truncated=truncated,
               usage=usage, seconds=round(time.time() - t0, 1), error=err, attempts=attempts)
    json.dump(rec, open(out_file, 'w'), indent=1, ensure_ascii=False)
    if fmt.get('kind') == 'code' and rec['parsed']:                 # the code alone, ready for the build step
        open(out_file[:-5] + '.c', 'w').write(rec['parsed']['code'] + '\n')
    return rec

def gen_failed(rec):
    """no reply was obtained: the request failed (network, timeout, HTTP error) or the reply is empty.
    A reply that is there but truncated or without usable code is the model's answer, not a failed generation."""
    return bool(rec.get('error')) or not (rec.get('response') or '').strip()

def query_capped(m, run, p, out_file, fmt, gen_attempts):
    """--gen-attempts N: at most N requests per task in total.  Each attempt is ONE request (no hidden retries inside);
    a failed attempt (gen_failed) is kept as <id>.attemptK.json and followed by the next one; when the last one fails too
    the task is stored with generation_failed = true and is not queried again by later runs."""
    run1 = dict(run, max_retries=1); log = []
    for k in range(1, gen_attempts + 1):
        rec = query(m, run1, p, out_file, fmt)
        log.append(dict(attempt=rec['attempts'], failed=gen_failed(rec), error=rec.get('error'), seconds=rec['seconds']))
        if not gen_failed(rec) or k == gen_attempts: break
        time.sleep(30 if '429' in (rec.get('error') or '') else 5)          # rate limit: give it time before the second request
    rec['generation_failed'] = gen_failed(rec); rec['attempt_log'] = log
    json.dump(rec, open(out_file, 'w'), indent=1, ensure_ascii=False)
    return rec

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--models', default='', help='comma-separated subset of model names from models.toml')
    ap.add_argument('--redo-bad', action='store_true', help='re-query replies that errored, were truncated or failed the format check')
    ap.add_argument('--workers', type=int, default=0, help='parallel requests per model (default: [run].workers)')
    ap.add_argument('--recheck', action='store_true', help='no model calls: re-run the format check on the stored replies (after a checker change)')
    ap.add_argument('--probe', action='store_true', help='send one tiny request per enabled model and print the model id the API actually serves')
    ap.add_argument('--gen-attempts', type=int, default=0, help='N > 0: at most N requests per task; a second one only when the first got no reply '
                                                                '(error or empty); still none -> generation_failed.  Default 0: [run].max_retries as before')
    a = ap.parse_args()
    if not a.scenario: ap.error('--scenario is required')
    scn = load_scenario(a.scenario); st = scn.stage(a.stage)
    if st.get('input_stage') and not a.from_model: ap.error(f'stage {a.stage} needs --from-model (whose {st["input_stage"]} replies were used)')
    stage_dir = scn.out(a.stage, a.from_model or None)
    pdir = os.path.join(stage_dir, 'prompts')
    ids = select_ids(a.ids, a.limit, [os.path.basename(f)[:4] for f in glob.glob(os.path.join(pdir, '[0-9]*.json'))])
    if not ids: sys.exit(f'no prompts in {pdir}: run build_prompts.py first')
    prompts = [json.load(open(os.path.join(pdir, i + '.json'), encoding='utf-8')) for i in ids]
    fmt = dict(kind=st.get('reply_format', 'headings' if st.get('required_headings') else 'json'), headings=st.get('required_headings', []))
    llm.SECRETS.update(scn.secrets())
    models = scn.models
    if os.environ.get('WB_LOCAL_PORT'):                       # vulcan/generate.sbatch: this job's own vLLM port
        import re as _re
        for m in models:
            if '127.0.0.1' in m.get('base_url', ''): m['base_url'] = _re.sub(r':\d+/', ':' + os.environ['WB_LOCAL_PORT'] + '/', m['base_url'])
    if a.models: models = [m for m in models if m['name'] in a.models.split(',')]

    if a.probe:
        for m in models:
            why = llm.usable(m)
            if why: print(f'[{m["name"]}] skipped: {why}'); continue
            served, err = llm.probe(m, llm.run_settings(scn.run, m))
            print(f'[{m["name"]}] config model = {m["model"]!r:30} served = {served!r}' + (f'  ERROR {err}' if err else ''))
        return

    if a.recheck:
        for d in sorted(glob.glob(os.path.join(stage_dir, 'responses', '*'))):
            if a.models and os.path.basename(d) not in a.models.split(','): continue
            changed = 0
            for f in glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json')):               # not the <id>.attemptN.json history
                r = json.load(open(f, encoding='utf-8'))
                if not r.get('response'): continue
                new = report.check(r['response'], fmt, next((p.get('c_name') or p['function'] for p in prompts if p['id'] == r['id']), r['function']))
                if new['format_ok'] != r.get('format_ok'):
                    changed += 1; r.update(new); json.dump(r, open(f, 'w'), indent=1, ensure_ascii=False)
                    if fmt.get('kind') == 'code' and r['parsed']: open(f[:-5] + '.c', 'w').write(r['parsed']['code'] + '\n')
            print(f'[{os.path.basename(d)}] rechecked, {changed} verdicts changed; summary: {report.summarize(d)}')
        return

    for m in models:
        why = llm.usable(m)
        if why: print(f'[{m["name"]}] skipped: {why}'); continue
        run = llm.run_settings(scn.run, m)
        d = os.path.join(stage_dir, 'responses', m['name']); os.makedirs(d, exist_ok=True)
        def done(p):
            f = os.path.join(d, p['id'] + '.json')
            if not (run.get('skip_existing', True) and os.path.exists(f)): return False
            return not (a.redo_bad and report.is_bad(json.load(open(f))))
        todo = [p for p in prompts if not done(p)]
        print(f'[{m["name"]}] {len(todo)} to query ({len(prompts) - len(todo)} already done)', flush=True)
        with ThreadPoolExecutor(max_workers=a.workers or run.get('workers', 4)) as ex:
            if a.gen_attempts > 0: futs = [ex.submit(query_capped, m, run, p, os.path.join(d, p['id'] + '.json'), fmt, a.gen_attempts) for p in todo]
            else: futs = [ex.submit(query, m, run, p, os.path.join(d, p['id'] + '.json'), fmt) for p in todo]
            for i, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                print(f'[{m["name"]}] {i}/{len(todo)} {r["id"]} {r["dll"]}!{r["function"]}: {report.status_line(r)}'
                      + (f'  [attempt {r["attempts"]}{", GENERATION FAILED" if r.get("generation_failed") else ""}]' if r.get('attempts', 1) > 1 or r.get('generation_failed') else ''), flush=True)
        print(f'[{m["name"]}] summary: {report.summarize(d)}')

if __name__ == '__main__':
    main()
