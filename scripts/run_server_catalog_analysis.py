"""Send a reviewed read-only script over SSH; retain aggregates locally, not the DB."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shlex


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True, help="Existing user@host SSH target")
    p.add_argument("--identity", type=Path, required=True)
    p.add_argument("--container", default="wanted-atlas-atlas-1")
    p.add_argument("--host-volume", help="Observed Docker data volume path; execute on host to survive application replacement")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not all(c.isalnum() or c in "-_" for c in args.container):
        raise ValueError("Invalid container name")
    source = Path(__file__).with_name("analyze_server_catalog.py").read_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_suffix(".partial.json")
    log = args.output.with_suffix(".progress.log")
    if args.host_volume:
        if not args.host_volume.startswith("/var/lib/docker/volumes/") or not args.host_volume.endswith("/_data"):
            raise ValueError("Expected observed Docker volume directory")
        remote = "sudo -n python3 - --db " + shlex.quote(args.host_volume + "/catalog.sqlite3") + " --graph " + shlex.quote(args.host_volume + "/graph-overview.json")
    else:
        remote = "sudo -n docker exec -i " + args.container + " python -"
    command = ["ssh", "-i", str(args.identity.resolve()), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "StrictHostKeyChecking=yes", args.host, remote]
    started = datetime.now(timezone.utc).isoformat()
    with pending.open("wb") as output, log.open("wb") as stderr:
        result = subprocess.run(command, input=source, stdout=output, stderr=stderr, timeout=1950)
    if result.returncode:
        raise SystemExit("Remote analysis failed. See " + str(log))
    report = json.loads(pending.read_bytes())
    assert report["validation"]["sql_counts_equal_scanned_counts"]
    report["execution"] = {"started_at": started, "script_sha256": hashlib.sha256(source).hexdigest(),
                           "source": "existing_server_host_volume" if args.host_volume else "existing_server_container", "database_downloaded": False,
                           "server_application_changed": False, "raw_observations_fetched": False}
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size,
                      "raw_rows": report["groups"]["all"]["raw_rows"],
                      "analysis_rows": report["groups"]["all"]["analysis_rows"],
                      "script_sha256": report["execution"]["script_sha256"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
