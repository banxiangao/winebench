"""Scenario configuration.

    scn = load_scenario('1.1')            # scenarios/scenario1.1/config.toml
    scn = load_scenario('/path/config.toml')
    scn.cfg            the parsed TOML
    scn.dir            directory of the config (templates are relative to it)
    scn.dataset        dataset directory
    scn.out(stage, from_model=None)   runs/<scenario>/<stage>[/from_<model>]
    scn.models         list of [[models]] (from [paths].models or inline)
    scn.stage(name)    the [stage.<name>] table
    scn.template(rel)  read a template file
"""
import os, sys
try: import tomllib
except ModuleNotFoundError:
    try: import tomli as tomllib
    except ModuleNotFoundError: sys.exit('need Python >= 3.11 or: pip install tomli')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))     # wine_bench/

class Scenario:
    def __init__(self, path):
        self.path = os.path.abspath(path); self.dir = os.path.dirname(self.path)
        self.name = os.path.basename(self.dir)
        self.cfg = tomllib.load(open(self.path, 'rb'))
        p = self.cfg.get('paths', {})
        self.dataset = self._rel(p.get('dataset', '../../dataset/wine500'))
        self._out = self._rel(p.get('out', f'../../runs/{self.name}'))
        # WB_SECRETS: a key file kept outside the project tree (vulcan/run_api.sbatch binds ~/.config/winebench/secrets.toml there)
        self.secrets_file = os.environ.get('WB_SECRETS') or self._rel(p.get('secrets', '../../secrets.toml'))
        if 'models' in self.cfg: self.models = self.cfg['models']
        else: self.models = tomllib.load(open(self._rel(p.get('models', '../models.toml')), 'rb')).get('models', [])
        self.run = self.cfg.get('run', {})

    def _rel(self, x): return os.path.normpath(os.path.join(self.dir, x))
    def out(self, stage, from_model=None):
        """runs/<scenario>/<stage>[/from_<model>] - a stage fed by another stage's replies is kept per upstream model"""
        d = os.path.join(self._out, stage)
        return os.path.join(d, f'from_{from_model}') if from_model else d
    def stage(self, name):
        st = self.cfg.get('stage', {}).get(name)
        if st is None: sys.exit(f'{self.path}: no [stage.{name}] section')
        return st
    def template(self, rel): return open(self._rel(rel), encoding='utf-8').read()
    def secrets(self):
        if not os.path.exists(self.secrets_file): return {}
        return tomllib.load(open(self.secrets_file, 'rb')).get('keys', {})

def load_scenario(name_or_path):
    if os.path.isfile(name_or_path): return Scenario(name_or_path)
    path = os.path.join(ROOT, 'scenarios', f'scenario{name_or_path}', 'config.toml')
    if not os.path.isfile(path): sys.exit(f'no such scenario: {name_or_path} ({path})')
    return Scenario(path)

def add_scenario_args(ap):
    ap.add_argument('--scenario', help='e.g. 1.1 -> scenarios/scenario1.1/config.toml, or a path to a config.toml')
    ap.add_argument('--stage', default='architect', help='stage of the scenario (default: architect)')
    ap.add_argument('--ids', default='', help='comma-separated record ids, e.g. 0001,0040')
    ap.add_argument('--limit', type=int, default=0, help='first N records only')
    ap.add_argument('--from-model', default='', help='for a stage that consumes another stage\'s replies (e.g. programmer <- architect): '
                                                   'which model\'s replies to use; output goes to <stage>/from_<model>/')
