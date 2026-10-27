"""Exercise the checked sparse-root-delta tools against a temporary fixture."""
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
fixture = repo / "research/hfs-fixture16-20261024/fixture.cdr"
make_delta = repo / "mac-build/make-marble-ios-root-delta.py"
apply_delta = repo / "mac-build/apply-marble-ios-root-delta.py"
with tempfile.TemporaryDirectory(prefix="marble-root-delta-") as tmp:
    work = Path(tmp)
    base = work / "base.cdr"
    changed = work / "changed.cdr"
    delta = work / "change.delta"
    output = work / "output.cdr"
    base.write_bytes(fixture.read_bytes())
    data = bytearray(base.read_bytes())
    data[4096 + 31:4096 + 38] = b"MARBLE!"
    changed.write_bytes(data)
    digest = hashlib.sha256(base.read_bytes()).hexdigest()
    subprocess.run([sys.executable, make_delta, base, changed, delta], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, apply_delta, base, delta, output,
                    "--base-sha256", digest], check=True, stdout=subprocess.DEVNULL)
    assert output.read_bytes() == changed.read_bytes()
print("root delta round-trip passed")
