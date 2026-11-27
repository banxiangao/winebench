#!/usr/bin/env python3
"""build_prompts.py - write the prompts of one stage of a scenario (no model calls).

    python3 scripts/build_prompts.py --scenario 1.1 --stage programmer                 # one-shot (wine_bench)
    python3 scripts/build_prompts.py --scenario 2.2 --stage mini_swe --ids 0001,0040   # agent (wine_agent)
    (--from-model: for a stage fed by another stage's replies; none of the current scenarios has one)

Output: runs/<scenario>/<stage>[/from_<model>]/prompts/<id>.json (what is sent) and <id>.md (readable).
A stage with [stage.<name>].input_stage set needs --from-model; records whose upstream reply is
missing or failed the format check are skipped (and counted).
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args
from bench.dataset import load_records
from bench.prompt import build_prompt, to_markdown

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    a = ap.parse_args()
    if not a.scenario: ap.error('--scenario is required')
    scn = load_scenario(a.scenario); st = scn.stage(a.stage)
    input_stage = st.get('input_stage')
    if input_stage and not a.from_model: ap.error(f'stage {a.stage} consumes the replies of stage {input_stage}: give --from-model <model>')
    out = os.path.join(scn.out(a.stage, a.from_model or None), 'prompts'); os.makedirs(out, exist_ok=True)
    n = total = skipped = 0
    for rec in load_records(scn.dataset, a.ids, a.limit):
        ctx = dict(from_model=a.from_model or None, upstream=None)
        if input_stage:
            f = os.path.join(scn.out(input_stage), 'responses', a.from_model, rec['id'] + '.json')
            up = json.load(open(f, encoding='utf-8')) if os.path.exists(f) else None
            if not up or not up.get('format_ok'): skipped += 1; continue
            ctx['upstream'] = up
        p = build_prompt(rec, scn, a.stage, ctx)
        json.dump(p, open(os.path.join(out, p['id'] + '.json'), 'w'), indent=1, ensure_ascii=False)
        open(os.path.join(out, p['id'] + '.md'), 'w').write(to_markdown(p))
        n += 1; total += len(p['system']) + sum(len(m['content']) for m in p['messages'])
    print(f'{n} prompts written to {out} (avg {total // max(n, 1)} chars)' + (f'; {skipped} skipped: no usable {input_stage} reply from {a.from_model}' if skipped else ''))

if __name__ == '__main__':
    main()
