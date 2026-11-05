"""Python-only scheduler bootstrap; captures even package import failures locally."""
from datetime import datetime
import os
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
out = Path(os.environ['LOCALAPPDATA']) / 'NYCU-e3-calendar' / 'out'
out.mkdir(parents=True, exist_ok=True)
logfile = out / 'bootstrap.log'
if logfile.exists() and logfile.stat().st_size > 2_000_000:
    logfile.replace(out / 'bootstrap.log.1')
with logfile.open('a', encoding='utf-8') as stream:
    sys.stdout = sys.stderr = stream
    print(f'[{datetime.now().astimezone().isoformat()}] BOOTSTRAP', flush=True)
    code = 1
    try:
        from nycu_e3.scheduled import main
        code = main(['--project-dir', str(root), *sys.argv[1:]])
        status_file = out / ('last-preview.json' if '--dry-run' in sys.argv else 'last-run.json')
        if status_file.exists():
            status = json.loads(status_file.read_text(encoding='utf-8'))
            print('STATUS started_at=' + status['started_at'] + ' success=' + str(status['success']), flush=True)
    except Exception as exc:
        # Never include exception payloads; Google may embed sensitive request data.
        print('STARTUP ERROR: ' + type(exc).__name__, flush=True)
        if isinstance(exc, ModuleNotFoundError):
            print('Missing Python module: ' + str(exc.name), flush=True)
    print('BOOTSTRAP END exit_code=' + str(code), flush=True)
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
raise SystemExit(code)
