import json
import urllib.request
from datetime import datetime, timezone
import boto3

ssm = boto3.client("ssm")
s3 = boto3.client("s3")


def load_config():
    """
    Runs once per Lambda container (cold start), not once per invocation.
    Lambda reuses warm containers across multiple 5-minute polls, so this
    avoids hitting Parameter Store on every single run.
    """
    bucket = ssm.get_parameter(Name="/vendor-status-monitor/s3-bucket")["Parameter"]["Value"]
    vendors_raw = ssm.get_parameter(Name="/vendor-status-monitor/vendors")["Parameter"]["Value"]
    vendors = json.loads(vendors_raw)
    return bucket, vendors


# Top-level, outside the handler — see docstring above for why
S3_BUCKET, VENDORS = load_config()
S3_PREFIX = "raw/status_checks"


def fetch_vendor_status(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "vendor-status-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def write_to_s3(vendor_name, payload, run_ts):
    dt = run_ts.strftime("%Y-%m-%d")
    ts = run_ts.strftime("%H%M%S")
    key = f"{S3_PREFIX}/vendor={vendor_name}/dt={dt}/{ts}.json"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def lambda_handler(event, context):
    run_ts = datetime.now(timezone.utc)
    succeeded, failed = [], []

    for vendor_name, url in VENDORS.items():
        try:
            payload = fetch_vendor_status(url)
            payload["_ingested_at"] = run_ts.isoformat()
            write_to_s3(vendor_name, payload, run_ts)
            succeeded.append(vendor_name)
        except Exception as e:
            print(f"ERROR fetching {vendor_name}: {e}")
            failed.append({"vendor": vendor_name, "error": str(e)})

    if len(failed) == len(VENDORS):
        raise RuntimeError("All vendor status checks failed")

    return {"succeeded": succeeded, "failed": failed}