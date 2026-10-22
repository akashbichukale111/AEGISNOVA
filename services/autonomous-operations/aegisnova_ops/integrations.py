"""Integration status (never reveals credential values) and non-destructive connection tests."""
import os

from . import SCHEMA_VERSION
from .aws import AwsConfig, make_client
from .providers import SnsProvider, WhatsAppCloudProvider
from .governance import UnwindAdapter


def environment_label(env=None):
    env = os.environ if env is None else env
    if env.get("AEGIS_PROFILE", "local").lower() != "aws":
        return {"profile": "local", "label": "LOCAL", "detail": "Local durable store, local queue, simulated/local providers"}
    cfg = AwsConfig(env)
    miss = cfg.missing(["AEGIS_AWS_ENABLED", "AWS_REGION", "AEGIS_STATE_MACHINE_ARN", "AEGIS_WORK_QUEUE_URL", "AEGIS_DLQ_URL"])
    if miss:
        return {"profile": "aws", "label": "AWS UNCONFIGURED", "detail": "missing: " + ", ".join(miss)}
    return {"profile": "aws", "label": "AWS CONFIGURED", "detail": "AWS adapters configured; this build does not make AWS the system of record (see ARCHITECTURE.md)"}


def integration_statuses(gov, env=None, auth_label="dev-token (NON-PRODUCTION)"):
    env = os.environ if env is None else env
    aws = AwsConfig(env)
    sns, wa = SnsProvider(env), WhatsAppCloudProvider(env)
    unwind = UnwindAdapter(env)

    def aws_item(name, keys, setup):
        miss = aws.missing(keys)
        return {"name": name, "kind": "aws", "state": "UNCONFIGURED" if miss else "CONFIGURED",
                "reason": ("missing env: " + ", ".join(miss)) if miss else "env present (connection not verified until you run Test)",
                "env_vars": keys, "setup": setup}

    items = [
        {"name": "local-store", "kind": "local", "state": "LOCAL", "reason": "SQLite durable store", "env_vars": ["AEGIS_DB_PATH"], "setup": "Defaults to ./.local/aegisnova.db"},
        {"name": "local-queue", "kind": "local", "state": "LOCAL", "reason": "Queue table in the local store; bounded depth, leases, DLQ", "env_vars": [], "setup": ""},
        {"name": "local-notification-sink", "kind": "local", "state": "LOCAL", "reason": "No external send is performed", "env_vars": [], "setup": ""},
        {"name": "notification-simulator", "kind": "local", "state": "SIMULATED", "reason": "Scripted email/SMS/WhatsApp behaviour; not provider evidence", "env_vars": [], "setup": ""},
        {"name": "governance-local-dev", "kind": "governance", "state": "SIMULATED", "reason": "TEST-ONLY decisions; never production authorization", "env_vars": ["AEGIS_LOCAL_DEV_GOVERNANCE_KEY"], "setup": "Used when AEGIS_GOVERNANCE is unset or 'local'"},
        {"name": "unwind-governance", "kind": "governance", "state": "CONFIGURED" if unwind.configured() else "UNCONFIGURED", "reason": unwind.status_reason(), "env_vars": UnwindAdapter.ENV + ["AEGIS_GOVERNANCE=unwind"], "setup": "Set AEGIS_GOVERNANCE=unwind plus UNWIND_* variables"},
        aws_item("aws-step-functions", ["AEGIS_AWS_ENABLED", "AWS_REGION", "AEGIS_STATE_MACHINE_ARN"], "Deploy infra/template.yaml yourself, then set the ARN"),
        aws_item("aws-sqs", ["AEGIS_AWS_ENABLED", "AWS_REGION", "AEGIS_WORK_QUEUE_URL", "AEGIS_DLQ_URL"], "Deploy infra/template.yaml yourself, then set the queue URLs"),
        {"name": "aws-sns", "kind": "aws", "state": "CONFIGURED" if sns.configured() else "UNCONFIGURED", "reason": sns.status_reason(), "env_vars": SnsProvider.ENV + ["SNS_SMS_ENABLED"], "setup": "SNS never carries WhatsApp. Allowlist required."},
        aws_item("aws-cloudwatch", ["AEGIS_AWS_ENABLED", "AWS_REGION"], "IAM: cloudwatch:PutMetricData scoped to the namespace"),
        {"name": "whatsapp-cloud-api", "kind": "provider", "state": "CONFIGURED" if wa.configured() else "UNCONFIGURED", "reason": wa.status_reason(), "env_vars": WhatsAppCloudProvider.ENV, "setup": "Official WhatsApp Business Platform Cloud API; template messages; webhook signature required"},
        {"name": "api-auth", "kind": "auth", "state": "LOCAL", "reason": auth_label, "env_vars": ["AEGIS_AUTH_MODE"], "setup": "Dev tokens are written to ./.local/dev-tokens.json"},
    ]
    for i in items:
        i["schema_version"] = SCHEMA_VERSION
    return items


def test_connection(name, env=None, clients=None, http=None):
    """Non-destructive: read-only calls only. Never sends a message. `clients` injects fakes in tests."""
    env = os.environ if env is None else env
    clients = clients or {}
    st = {i["name"]: i for i in integration_statuses(None, env)}
    if name not in st:
        return {"ok": False, "state": "UNKNOWN", "reason": "unknown integration"}
    item = st[name]
    if item["state"] == "UNCONFIGURED":
        return {"ok": False, "state": "UNCONFIGURED", "reason": item["reason"]}
    if item["kind"] in ("local", "auth", "governance"):
        return {"ok": True, "state": item["state"], "reason": "local component; no external call made"}
    aws = AwsConfig(env)
    try:
        if name == "aws-sqs":
            c = clients.get("sqs") or make_client("sqs", aws.region)
            c.get_queue_attributes(QueueUrl=aws.work_queue_url, AttributeNames=["QueueArn"])
        elif name == "aws-step-functions":
            c = clients.get("stepfunctions") or make_client("stepfunctions", aws.region)
            c.describe_state_machine(stateMachineArn=aws.state_machine_arn)
        elif name == "aws-sns":
            c = clients.get("sns") or make_client("sns", aws.region)
            c.get_topic_attributes(TopicArn=env.get("SNS_EMAIL_TOPIC_ARN", ""))
        elif name == "aws-cloudwatch":
            c = clients.get("cloudwatch") or make_client("cloudwatch", aws.region)
            c.list_metrics(Namespace=aws.namespace)
        elif name == "whatsapp-cloud-api":
            wa = WhatsAppCloudProvider(env, http)
            status, _ = wa.http("GET", f"https://graph.facebook.com/{wa.api_version}/{wa.phone_id}", {"Authorization": f"Bearer {wa.token}"}, None)
            if status >= 300:
                return {"ok": False, "state": "CONFIGURED", "reason": f"read-only probe returned HTTP {status}"}
        else:
            return {"ok": False, "state": item["state"], "reason": "no probe defined"}
    except Exception as e:
        from .util import redact
        return {"ok": False, "state": "CONFIGURED", "reason": "probe failed: " + redact(type(e).__name__)}
    return {"ok": True, "state": "CONFIGURED", "reason": "read-only probe succeeded (no message sent)"}
