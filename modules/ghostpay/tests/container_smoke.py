"""Executable container acceptance harness; leaves its container for browser tests.

Remove the owned container using the ID in GHOSTPAY_TEST_WORK_DIR/container-id.
"""

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from contracts.fixtures import TENANT_ALPHA_ID

root = Path(os.environ.get("GHOSTPAY_TEST_WORK_DIR", "/tmp/ghostpay-acceptance"))
root.mkdir(parents=True, exist_ok=True)
image = os.environ.get("GHOSTPAY_TEST_IMAGE", "ghostpay:review")
token = secrets.token_urlsafe(48)
credentials = {"GHOSTPAY_TOKENS": json.dumps({token: str(TENANT_ALPHA_ID)})}
env_file = root / "container.env"
fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("GHOSTPAY_TOKENS=" + credentials["GHOSTPAY_TOKENS"] + "\n")
(root / "token").write_text(token)
(root / "token").chmod(0o600)
docker = ["docker", "--host=unix:///var/run/docker.sock"]
missing = subprocess.run(
    [*docker, "run", "--rm", image],
    capture_output=True,
    text=True,
    timeout=30,
    check=False,
)
assert missing.returncode != 0 and "Configure GHOSTPAY_TOKENS" in missing.stderr
cid = subprocess.check_output(
    [
        *docker,
        "run",
        "-d",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=128",
        "--tmpfs",
        "/tmp:size=16m,mode=1777",
        "--env-file",
        str(env_file),
        "-p",
        "127.0.0.1:8765:8000",
        image,
    ],
    text=True,
).strip()
(root / "container-id").write_text(cid)
base = "http://127.0.0.1:8765"
for attempt in range(60):
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=2) as response:
            assert response.status == 200
        break
    except (OSError, urllib.error.URLError):
        time.sleep(0.2)
else:
    raise RuntimeError("Container did not start")


def call(path, body=None, authenticated=True):
    headers = {"Authorization": "Bearer " + token} if authenticated else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


status, example = call("/v1/ghostpay/example")
assert status == 200
assert call("/v1/ghostpay/example", authenticated=False)[0] == 401
status, result = call("/v1/ghostpay/replay", example["request"])
assert status == 200 and result["consistency_status"] == "CONSISTENT"
status, result = call(
    "/v1/ghostpay/simulate",
    {"request": example["request"], "overrides": {"per_tx_limit_minor": 3000}},
)
assert (
    status == 200
    and result["recomputed_outcome"] == "DENY"
    and not result["executed_payment"]
)
status, result = call(
    "/v1/ghostpay/simulate",
    {"request": example["request"], "overrides": {"amount_override_minor": -1}},
)
assert status == 400
config = json.loads(subprocess.check_output([*docker, "inspect", cid], text=True))[0]
assert (
    config["Config"]["User"] == "10001:10001" and config["HostConfig"]["ReadonlyRootfs"]
)
assert (
    subprocess.check_output(
        [*docker, "exec", cid, "python", "-c", "import os; print(os.getuid())"],
        text=True,
    ).strip()
    == "10001"
)
print(
    "Container acceptance passed: fail-closed startup, health, authentication, replay, simulation, invalid amount, non-root read-only runtime"
)
