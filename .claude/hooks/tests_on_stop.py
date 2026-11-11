"""Hook Stop : relance pytest si du Python a changé ; code 2 = Claude doit corriger avant de finir."""
import json
import os
import subprocess
import sys

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

py = os.path.join(root, ".venv", "Scripts", "python.exe")
r = subprocess.run([py, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                   cwd=root, capture_output=True, text=True, timeout=300)
if r.returncode == 0:
    sys.exit(0)
print("Les tests échouent, corrige avant de terminer :\n" + (r.stdout + r.stderr)[-3000:], file=sys.stderr)
sys.exit(2)
