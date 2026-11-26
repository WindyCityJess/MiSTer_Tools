# Scripted UI test for "Defer": fakes every dialog call and writes only to copies under /tmp/ucf_test.
# Run on the MiSTer:  python3 tests/test_ui_defer.py   (set UCF_DIR if ucf.py is elsewhere)
# Flow: continue past the warning (if shown) -> Computer: defer all, switch #1 to install -> continue
# + confirm. Then checks the deferred terms are in the filter, releases them the way the launcher
# does after Update All, and checks the ini filter is back to what it was.
# Needs at least two new Computer cores in the current databases.
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
ucf.DEFERRED = WORK + '/conf/deferred.json'
shutil.rmtree(ucf.CONF_DIR, ignore_errors=True)


def filter_terms():
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None)
    cp.read(ucf.MAIN_INI)
    return cp['mister'].get('filter', '').split() if cp.has_section('mister') else []


BEFORE = filter_terms()
script = [
    ('--menu', 0, '2'), ('--menu', 0, '~'), ('--menu', 0, '1'), ('--menu', 0, 'D'),  # defer all, #1 -> install
    ('--menu', 0, 'G'), ('--yesno', 0, ''),
]
log = []


def fake(args):
    kind = next(a for a in args if a in ('--menu', '--yesno', '--msgbox', '--textbox'))
    title = args[args.index('--title') + 1]
    log.append('%s %s' % (kind, title))
    if kind == '--msgbox':
        return 0, ''
    if kind == '--yesno' and title.startswith('Warning'):
        return 0, ''
    exp = script.pop(0)
    assert exp[0] == kind, (exp, kind, title)
    return exp[1], exp[2]


ucf.dlg = fake
os.system = lambda c: 0
rc = ucf.run_ui()
print('\n'.join(log))
print('RC', rc, 'script left', script)
added = filter_terms()[len(BEFORE):]
pending = ucf.load_deferred()
print('terms added for this run:', added)
print('deferred.json:', [e['term'] for e in pending])
print('blocked.json entries:', len(ucf.load_state()))
assert rc == 0 and not script
assert pending and sorted('!' + e['term'] for e in pending) == sorted(added)
assert not ucf.load_state(), 'defer must not record permanent blocks'

ucf.release_deferred()  # what the launcher runs after Update All
print('after release:', filter_terms()[len(BEFORE):], 'deferred.json exists:', os.path.exists(ucf.DEFERRED))
assert filter_terms() == BEFORE
assert not os.path.exists(ucf.DEFERRED)
print(open(ucf.HISTORY).read())
print('PASS')
