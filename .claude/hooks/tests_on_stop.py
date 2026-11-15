"""Hook Stop : relance pytest si du Python a changé ; code 2 = Claude doit corriger avant de finir."""
import glob
import hashlib
import json
import os
import subprocess
import sys

sys.stderr.reconfigure(encoding="utf-8")

root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
if data.get("stop_hook_active"):          # déjà relancé une fois par ce hook : ne pas boucler
    sys.exit(0)


def git(*args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


changed = git("status", "--porcelain", "--", "*.py") + git("diff", "--name-only", "dev...HEAD", "--", "*.py")
if not changed.strip():
    sys.exit(0)

# rien n'a bougé depuis la dernière réussite : pas de relance (évite ~14 s à chaque fin de réponse)
h = hashlib.sha1()
for f in sorted(glob.glob(os.path.join(root, "src", "**", "*.py"), recursive=True)
                + glob.glob(os.path.join(root, "tests", "*.py"))):
    h.update(f.encode())
    with open(f, "rb") as fh:
        h.update(fh.read())
stamp = os.path.join(root, "logs", "tests_ok.txt")
try:
    with open(stamp, encoding="utf-8") as fh:
        if fh.read() == h.hexdigest():
            sys.exit(0)
except OSError:
    pass

py = os.path.join(root, ".venv", "Scripts", "python.exe")
r = subprocess.run([py, "-m", "pytest", "-q", "-x", "--no-header", "--tb=short", "-p", "no:cacheprovider"],
                   cwd=root, capture_output=True, text=True, timeout=300)
if r.returncode == 0:
    try:
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(h.hexdigest())             # empreinte du code qui passe
    except OSError:
        pass
    sys.exit(0)
print("Les tests échouent, corrige avant de terminer :\n" + (r.stdout + r.stderr)[-1500:], file=sys.stderr)
sys.exit(2)
