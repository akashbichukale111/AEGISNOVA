"""AWS adapters (Step Functions, SQS, CloudWatch). Clients are INJECTED; boto3 is imported lazily and only
when AEGIS_AWS_ENABLED=true. Nothing here creates resources. Tests use fake clients only."""
import os

from .util import redact, new_id

CALLBACK_TOKEN_NOTE = "Task tokens are stored server-side, single-use, never returned by the API, logged, or put in notifications."


class AwsConfig:
    ENV = ["AEGIS_AWS_ENABLED", "AWS_REGION", "AEGIS_STATE_MACHINE_ARN", "AEGIS_WORK_QUEUE_URL", "AEGIS_DLQ_URL", "AEGIS_CW_NAMESPACE"]

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.enabled = env.get("AEGIS_AWS_ENABLED", "").lower() == "true"
        self.region = env.get("AWS_REGION", "")
        self.state_machine_arn = env.get("AEGIS_STATE_MACHINE_ARN", "")
        self.work_queue_url = env.get("AEGIS_WORK_QUEUE_URL", "")
        self.dlq_url = env.get("AEGIS_DLQ_URL", "")
        self.namespace = env.get("AEGIS_CW_NAMESPACE", "AEGISNOVA/Operations")

    def missing(self, keys):
        vals = {"AEGIS_AWS_ENABLED": self.enabled, "AWS_REGION": self.region, "AEGIS_STATE_MACHINE_ARN": self.state_machine_arn,
                "AEGIS_WORK_QUEUE_URL": self.work_queue_url, "AEGIS_DLQ_URL": self.dlq_url}
        return [k for k in keys if not vals[k]]


def make_client(service, region):
    import boto3  # lazy
    return boto3.client(service, region_name=region)


class OrchestrationAdapter:
    """Provider-neutral orchestration interface (local engine and Step Functions implement it)."""
    def start(self, run): raise NotImplementedError
    def cancel(self, run_id, reason): raise NotImplementedError
    def resume(self, run_id, approval_id): raise NotImplementedError
    def status(self, run_id): raise NotImplementedError


class StepFunctionsAdapter(OrchestrationAdapter):
    """Step Functions Standard with .waitForTaskToken approval waits. Token handling is server-side only."""
    def __init__(self, client, state_machine_arn, store=None, clock=None):
        self.c, self.arn, self.store, self.clock = client, state_machine_arn, store, clock

    def start(self, run):
        # execution name == run id => StartExecution is idempotent for the same name+input
        r = self.c.start_execution(stateMachineArn=self.arn, name=run["id"],
                                   input=f'{{"run_id":"{run["id"]}","correlation_id":"{run["correlation_id"]}"}}')
        return r.get("executionArn")

    def cancel(self, run_id, reason):
        self.c.stop_execution(executionArn=f"{self.arn.replace(':stateMachine:', ':execution:')}:{run_id}", error="Cancelled", cause=redact(reason)[:200])

    def register_callback_token(self, approval_id, run_id, token):
        with self.store.tx():
            self.store.x("INSERT OR REPLACE INTO callback_tokens(approval_id,run_id,token,created_at) VALUES(?,?,?,?)",
                         (approval_id, run_id, token, self.clock.now_iso()))

    def resume(self, run_id, approval_id):
        """Call ONLY after the engine validated a GRANTED decision. Token is consumed exactly once."""
        with self.store.tx():
            row = self.store.one("SELECT * FROM callback_tokens WHERE approval_id=? AND run_id=? AND used_at IS NULL", (approval_id, run_id))
            if not row:
                raise LookupError("no unused callback token for this approval/run (replay or unknown)")
            self.store.x("UPDATE callback_tokens SET used_at=?, token='' WHERE approval_id=?", (self.clock.now_iso(), approval_id))
        self.c.send_task_success(taskToken=row["token"], output='{"approved":true}')

    def fail(self, run_id, approval_id, error="ApprovalDenied"):
        with self.store.tx():
            row = self.store.one("SELECT * FROM callback_tokens WHERE approval_id=? AND run_id=? AND used_at IS NULL", (approval_id, run_id))
            if not row:
                return False
            self.store.x("UPDATE callback_tokens SET used_at=?, token='' WHERE approval_id=?", (self.clock.now_iso(), approval_id))
        self.c.send_task_failure(taskToken=row["token"], error=error, cause="governance decision was not a valid grant")
        return True

    def status(self, run_id):
        r = self.c.describe_execution(executionArn=f"{self.arn.replace(':stateMachine:', ':execution:')}:{run_id}")
        return r.get("status")


class SqsAdapter:
    """Work queue + DLQ over SQS. Long polling, bounded batches, idempotent consumer (dedupe by message attribute)."""
    def __init__(self, client, queue_url, dlq_url, dlq_arn=None, source_arn=None):
        self.c, self.q, self.dlq, self.dlq_arn, self.source_arn = client, queue_url, dlq_url, dlq_arn, source_arn

    def send(self, body, dedupe_key, correlation_id):
        return self.c.send_message(QueueUrl=self.q, MessageBody=body, MessageAttributes={
            "dedupe_key": {"DataType": "String", "StringValue": dedupe_key},
            "correlation_id": {"DataType": "String", "StringValue": correlation_id}})["MessageId"]

    def receive(self, max_messages=10):
        r = self.c.receive_message(QueueUrl=self.q, MaxNumberOfMessages=min(max_messages, 10), WaitTimeSeconds=20,
                                   MessageAttributeNames=["All"], AttributeNames=["ApproximateReceiveCount"])
        return r.get("Messages", [])

    def delete(self, receipt_handle):
        self.c.delete_message(QueueUrl=self.q, ReceiptHandle=receipt_handle)

    def depth(self):
        a = self.c.get_queue_attributes(QueueUrl=self.q, AttributeNames=["ApproximateNumberOfMessages", "ApproximateAgeOfOldestMessage"])["Attributes"]
        return {"depth": int(a.get("ApproximateNumberOfMessages", 0)), "oldest_age_s": int(a.get("ApproximateAgeOfOldestMessage", 0))}

    def redrive(self, max_per_second=1):
        """Audited, rate-capped DLQ->source redrive via SQS message move task (cap enforced by SQS)."""
        if not (self.dlq_arn and self.source_arn):
            raise ValueError("dlq_arn and source_arn required")
        if not (1 <= max_per_second <= 10):
            raise ValueError("max_per_second must be 1..10")
        return self.c.start_message_move_task(SourceArn=self.dlq_arn, DestinationArn=self.source_arn,
                                              MaxNumberOfMessagesPerSecond=max_per_second)["TaskHandle"]


_UNITS = {"age": "Seconds", "_s": "Seconds", "rate": "None"}


class CloudWatchEmitter:
    """Publishes ONLY measured metrics to CloudWatch (never fabricated). Local mode uses no emitter."""
    def __init__(self, client, namespace="AEGISNOVA/Operations"):
        self.c, self.ns = client, namespace

    def emit(self, snapshot):
        data = []
        for name, v in snapshot.items():
            if v is None:
                continue
            base, _, ch = name.partition(":")
            unit = "Seconds" if base.endswith("_s") else "Count"
            item = {"MetricName": base, "Value": float(v), "Unit": "None" if "rate" in base else unit}
            if ch:
                item["Dimensions"] = [{"Name": "Channel", "Value": ch}]
            data.append(item)
        sent = 0
        for i in range(0, len(data), 20):
            self.c.put_metric_data(Namespace=self.ns, MetricData=data[i:i + 20])
            sent += len(data[i:i + 20])
        return sent
