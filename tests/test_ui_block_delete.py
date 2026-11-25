# Scripted UI test for "Block + delete": fakes every dialog call; the ini, state and every
# deleted file live under /tmp/ucf_test (installed files are recreated as empty fakes there).
# Run on the MiSTer:  python3 tests/test_ui_block_delete.py   (set UCF_DIR if ucf.py is elsewhere)
# Needs at least one shared-tag item in the current databases.
import configparser
import os
import shutil
import sys

UCF_DIR = os.environ.get('UCF_DIR', '/media/fat/Scripts/.config/update_all_check_first')
WORK = '/tmp/ucf_test'
os.makedirs(WORK, exist_ok=True)
sys.dont_write_bytecode = True  # keep the helper folder clean
sys.path.insert(0, UCF_DIR)
import ucf  # noqa: E402

shutil.copy('/media/fat/downloader.ini', WORK + '/test_downloader.ini')
ucf.MAIN_INI = WORK + '/test_downloader.ini'
ucf.CONF_DIR = WORK + '/conf'
ucf.STATE = WORK + '/conf/blocked.json'
ucf.HISTORY = WORK + '/conf/history.log'
shutil.rmtree(ucf.CONF_DIR, ignore_errors=True)
FAKE = WORK + '/fakefat'
shutil.rmtree(FAKE, ignore_errors=True)


def filter_terms():
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None)
    cp.read(ucf.MAIN_INI)
    return cp['mister'].get('filter', '').split() if cp.has_section('mister') else []


BEFORE = len(filter_terms())
real_analyze = ucf.analyze


def analyze(progress=print):
    a = real_analyze(progress)
    ucf.BASE = FAKE  # deletions now happen in the fake tree only
    for it in a['shared']:
        for p in it['installed']:
            full = os.path.join(FAKE, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, 'w').close()
    print('shared items:', [(i['label'], i['term'], len(i['installed'])) for i in a['shared']])
    return a


ucf.analyze = analyze
script = [
    ('--yesno', 0, ''),                                                              # warning: continue
    ('--menu', 0, 'W'), ('--menu', 0, '1'), ('--yesno', 0, ''), ('--menu', 0, 'D'),  # shared #1 -> block + delete
    ('--menu', 0, 'G'), ('--yesno', 0, ''),                                          # continue + confirm
]
log = []


def fake(args):
    kind = next(a for a in args if a in ('--menu', '--yesno', '--msgbox', '--textbox'))
    title = args[args.index('--title') + 1]
    log.append('%s %s' % (kind, title))
    if kind == '--msgbox':
        return 0, ''
    exp = script.pop(0)
    assert exp[0] == kind, (exp, kind, title)
    return exp[1], exp[2]


ucf.dlg = fake
os.system = lambda c: 0
rc = ucf.run_ui()
print('\n'.join(log))
print('RC', rc, 'script left', script)
print('added terms:', filter_terms()[BEFORE:])
print(open(ucf.HISTORY).read()[:1500])
left = [os.path.join(r, f) for r, d, fs in os.walk(FAKE) for f in fs]
print('fake files left:', len(left))
