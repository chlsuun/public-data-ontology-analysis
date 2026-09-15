"""Bounded official-source downloads with immutable bytes and request receipts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error


def fetch(url, output, accept="application/json", limit=12_000_000):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    if output.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["url"] == url, "Cached URL differs"
        assert receipt["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
        return receipt
    receipt = {"url": url, "started_at": datetime.now(timezone.utc).isoformat(),
               "accept": accept, "byte_limit": limit}
    try:
        request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "PublicDataOntology-Research/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            receipt.update(status=response.status, final_url=response.url,
                           headers={k: v for k, v in response.headers.items() if k.lower() in
                                    {"content-type", "last-modified", "etag", "date", "content-length"}})
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Response exceeds bounded download limit")
        output.write_bytes(body)
        receipt.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), file=output.name)
    except Exception as error:
        receipt.update(error=str(error), error_type=type(error).__name__)
        if isinstance(error, urllib.error.HTTPError):
            receipt["status"] = error.code
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output")
    parser.add_argument("--accept", default="application/json")
    args = parser.parse_args()
    print(json.dumps(fetch(args.url, args.output, args.accept), ensure_ascii=False))
