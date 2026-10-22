"""Notification providers: local sink, simulators, AWS SNS (email/SMS), WhatsApp Cloud API.

Provider contract: send(notification_dict) -> ProviderResult. Providers never log message bodies,
never return secrets, and distinguish API ACCEPTANCE from DELIVERY (delivery comes only from receipts)."""
import hashlib
import hmac
import json
import os
import re
import socket
import urllib.request
import urllib.error

from .util import redact, new_id

ACCEPTED, TRANSIENT, PERMANENT, AMBIGUOUS = "ACCEPTED", "TRANSIENT", "PERMANENT", "AMBIGUOUS"


class ProviderResult:
    def __init__(self, outcome, message_id=None, error_class=None, error=None):
        self.outcome, self.message_id, self.error_class = outcome, message_id, error_class
        self.error = redact(error) if error else None


def build_message(n):
    """Minimal templated body. Never includes tokens, secrets or raw payloads."""
    params = json_params(n)
    if n["template"] == "workflow.completed":
        return f"AEGISNOVA: workflow {n.get('run_id')} completed."
    if n["template"] == "test":
        return "AEGISNOVA test notification."
    return f"AEGISNOVA notification ({str(n['template'])[:40]}) {str(params.get('ref', ''))[:40]}".strip()


def json_params(n):
    try:
        return json.loads(n.get("params_json") or "{}")
    except ValueError:
        return {}


class Provider:
    name = "abstract"
    mode = "LOCAL"
    channels = ()
    supports_receipts = False

    def configured(self):
        return True

    def status_reason(self):
        return ""

    def validate_destination(self, channel, dest):
        return None  # None = ok else error string

    def send(self, n):
        raise NotImplementedError


class LocalSink(Provider):
    """Writes nothing externally. Everything is retained only in the local DB. Mode LOCAL."""
    name, mode, channels = "local-sink", "LOCAL", ("local_sink", "email", "sms", "whatsapp")

    def status_reason(self):
        return "Local sink: no external send is ever performed."

    def send(self, n):
        return ProviderResult(ACCEPTED, message_id="sink-" + n["id"])


class Simulated(Provider):
    """Deterministic simulator. Destination hints drive behaviour: fail-transient, fail-permanent,
    ambiguous, flaky-N (first N attempts fail transiently). Mode SIMULATED. Never touches a network."""
    name, mode, channels = "simulator", "SIMULATED", ("email", "sms", "whatsapp", "local_sink")
    supports_receipts = True

    def status_reason(self):
        return "Simulator: behaviour is scripted; results are NOT provider evidence."

    def send(self, n):
        d = (n.get("destination") or "").lower()
        if "fail-permanent" in d:
            return ProviderResult(PERMANENT, error_class="permanent", error="simulated invalid recipient")
        if "ambiguous" in d:
            return ProviderResult(AMBIGUOUS, error_class="ambiguous", error="simulated timeout after request sent")
        m = re.search(r"flaky-(\d+)", d)
        if "fail-transient" in d or (m and n["attempts"] <= int(m.group(1))):
            return ProviderResult(TRANSIENT, error_class="transient", error="simulated throttling")
        return ProviderResult(ACCEPTED, message_id="sim-" + new_id("m"))


def classify_aws_exception(exc):
    """Map boto3/botocore-style exceptions to provider outcomes without importing botocore."""
    code = ""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = resp.get("Error", {}).get("Code", "") or ""
    name = type(exc).__name__
    if code in ("Throttling", "ThrottlingException", "InternalError", "InternalFailure", "ServiceUnavailable",
                "ServiceUnavailableException", "RequestLimitExceeded", "KMSThrottling"):
        return TRANSIENT, code
    if code in ("InvalidParameter", "InvalidParameterValue", "AuthorizationError", "NotFound", "OptedOut",
                "OptedOutException", "InvalidClientTokenId", "AccessDenied", "KMSAccessDenied", "EndpointDisabled"):
        return PERMANENT, code
    if name in ("ConnectTimeoutError", "EndpointConnectionError", "ConnectionRefusedError") or isinstance(exc, ConnectionError):
        return TRANSIENT, name          # request never reached the service
    if name in ("ReadTimeoutError",) or isinstance(exc, (TimeoutError, socket.timeout)):
        return AMBIGUOUS, name          # may have been accepted -> do NOT blindly resend
    return TRANSIENT, name or "error"


E164 = re.compile(r"^\+[1-9]\d{7,14}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


class SnsProvider(Provider):
    """AWS SNS publish for email (to a topic) and SMS (direct). Mode REAL. Client is injectable.
    SNS NEVER delivers WhatsApp. Publish success == ACCEPTED only; no delivery is inferred."""
    name, mode, channels = "aws-sns", "REAL", ("email", "sms")
    ENV = ["AEGIS_AWS_ENABLED", "AWS_REGION", "SNS_EMAIL_TOPIC_ARN", "AEGIS_RECIPIENT_ALLOWLIST"]

    def __init__(self, env=None, client=None):
        env = os.environ if env is None else env
        self.enabled = env.get("AEGIS_AWS_ENABLED", "").lower() == "true"
        self.region = env.get("AWS_REGION", "")
        self.topic = env.get("SNS_EMAIL_TOPIC_ARN", "")
        self.sms_enabled = env.get("SNS_SMS_ENABLED", "").lower() == "true"
        self.allow = {x.strip().lower() for x in env.get("AEGIS_RECIPIENT_ALLOWLIST", "").split(",") if x.strip()}
        self._client = client

    def configured(self):
        return self.enabled and bool(self.region) and bool(self.allow) and (bool(self.topic) or self.sms_enabled)

    def status_reason(self):
        if not self.enabled:
            return "AEGIS_AWS_ENABLED is not 'true'"
        miss = [k for k, v in (("AWS_REGION", self.region), ("AEGIS_RECIPIENT_ALLOWLIST", self.allow)) if not v]
        if not (self.topic or self.sms_enabled):
            miss.append("SNS_EMAIL_TOPIC_ARN or SNS_SMS_ENABLED=true")
        return ("missing: " + ", ".join(miss)) if miss else "configured (not live-tested in this build)"

    def validate_destination(self, channel, dest):
        if channel == "email":
            if not EMAIL.match(dest or ""):
                return "invalid email address"
        elif channel == "sms":
            if not E164.match(dest or ""):
                return "SMS destination must be E.164 (+<country><number>)"
        else:
            return "SNS supports email and sms only"
        if self.allow and dest.lower() not in self.allow:
            return "destination not in recipient allowlist"
        return None

    def client(self):
        if self._client is None:
            import boto3  # lazy: only when a real send is explicitly configured
            self._client = boto3.client("sns", region_name=self.region)
        return self._client

    def send(self, n):
        if not self.configured():
            return ProviderResult(PERMANENT, error_class="unconfigured", error="SNS provider unconfigured")
        err = self.validate_destination(n["channel"], n["destination"])
        if err:
            return ProviderResult(PERMANENT, error_class="policy", error=err)
        msg = build_message(n)
        try:
            if n["channel"] == "email":
                if not self.topic:
                    return ProviderResult(PERMANENT, error_class="unconfigured", error="SNS_EMAIL_TOPIC_ARN missing")
                r = self.client().publish(TopicArn=self.topic, Subject="AEGISNOVA notification", Message=msg,
                                          MessageAttributes={"notification_id": {"DataType": "String", "StringValue": n["id"]}})
            else:
                if not self.sms_enabled:
                    return ProviderResult(PERMANENT, error_class="unconfigured", error="SMS not enabled")
                r = self.client().publish(PhoneNumber=n["destination"], Message=msg, MessageAttributes={
                    "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}})
            return ProviderResult(ACCEPTED, message_id=r.get("MessageId"))
        except Exception as e:  # classified; message redacted
            outcome, code = classify_aws_exception(e)
            return ProviderResult(outcome, error_class={TRANSIENT: "transient", PERMANENT: "permanent", AMBIGUOUS: "ambiguous"}[outcome],
                                  error=f"{code}")


# ---- WhatsApp Business Platform (Cloud API) --------------------------------------------

GRAPH_HOST = "https://graph.facebook.com"


def urllib_http(method, url, headers, body, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # TLS verified by default context
            raw = r.read(65536)
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(65536) or b"null")
        except ValueError:
            return e.code, None


class WhatsAppCloudProvider(Provider):
    """Official WhatsApp Business Platform Cloud API (template messages only).
    Implemented against the public contract; NOT live-tested. UNCONFIGURED without env."""
    name, mode, channels = "whatsapp-cloud", "REAL", ("whatsapp",)
    supports_receipts = True
    ENV = ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET",
           "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "WHATSAPP_TEMPLATE_NAME", "WHATSAPP_RECIPIENT_ALLOWLIST"]

    def __init__(self, env=None, http=None):
        env = os.environ if env is None else env
        self.token = env.get("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_id = env.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.app_secret = env.get("WHATSAPP_APP_SECRET", "")
        self.verify_token = env.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
        self.template = env.get("WHATSAPP_TEMPLATE_NAME", "")
        self.lang = env.get("WHATSAPP_TEMPLATE_LANG", "en")
        self.api_version = env.get("WHATSAPP_API_VERSION", "v21.0")
        self.allow = {x.strip() for x in env.get("WHATSAPP_RECIPIENT_ALLOWLIST", "").split(",") if x.strip()}
        self.http = http or urllib_http

    def configured(self):
        return all([self.token, self.phone_id, self.app_secret, self.verify_token, self.template, self.allow])

    def status_reason(self):
        miss = [n for n, v in zip(self.ENV, [self.token, self.phone_id, self.app_secret, self.verify_token,
                                             self.template, self.allow]) if not v]
        return ("missing env: " + ", ".join(miss)) if miss else "configured (not live-tested in this build)"

    def validate_destination(self, channel, dest):
        if channel != "whatsapp":
            return "WhatsAppCloudProvider handles the whatsapp channel only"
        if not E164.match(dest or ""):
            return "destination must be E.164"
        if dest not in self.allow:
            return "destination not in WHATSAPP_RECIPIENT_ALLOWLIST"
        return None

    def send(self, n):
        if not self.configured():
            return ProviderResult(PERMANENT, error_class="unconfigured", error="WhatsApp provider unconfigured")
        err = self.validate_destination(n["channel"], n["destination"])
        if err:
            return ProviderResult(PERMANENT, error_class="policy", error=err)
        url = f"{GRAPH_HOST}/{self.api_version}/{self.phone_id}/messages"
        body = {"messaging_product": "whatsapp", "to": n["destination"].lstrip("+"), "type": "template",
                "template": {"name": self.template, "language": {"code": self.lang}}}
        try:
            status, data = self.http("POST", url, {"Authorization": f"Bearer {self.token}"}, body)
        except (ConnectionError,) as e:
            return ProviderResult(TRANSIENT, error_class="transient", error=type(e).__name__)
        except (TimeoutError, socket.timeout) as e:
            return ProviderResult(AMBIGUOUS, error_class="ambiguous", error=type(e).__name__)
        except Exception as e:
            return ProviderResult(TRANSIENT, error_class="transient", error=type(e).__name__)
        if 200 <= status < 300 and isinstance(data, dict) and data.get("messages"):
            return ProviderResult(ACCEPTED, message_id=str(data["messages"][0].get("id")))
        code = ""
        if isinstance(data, dict):
            code = str((data.get("error") or {}).get("code", ""))
        if status == 429 or status >= 500 or code in ("4", "80007", "130429"):
            return ProviderResult(TRANSIENT, error_class="transient", error=f"http {status} code {code}")
        return ProviderResult(PERMANENT, error_class="permanent", error=f"http {status} code {code}")

    # webhook helpers -------------------------------------------------------------
    def verify_signature(self, raw_body, header):
        if not self.app_secret or not header or not header.startswith("sha256="):
            return False
        exp = hmac.new(self.app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(exp, header[7:])

    def verify_challenge(self, params):
        if params.get("hub.mode") == "subscribe" and self.verify_token and \
                hmac.compare_digest(params.get("hub.verify_token", ""), self.verify_token):
            return params.get("hub.challenge", "")
        return None

    @staticmethod
    def parse_statuses(payload):
        out = []
        for entry in (payload.get("entry") or []):
            for ch in (entry.get("changes") or []):
                for st in ((ch.get("value") or {}).get("statuses") or []):
                    mid, status, ts = st.get("id"), st.get("status"), str(st.get("timestamp", ""))
                    if mid and status in ("sent", "delivered", "read", "failed"):
                        out.append({"provider_message_id": mid, "status": status, "provider_ts": ts,
                                    "provider_event_id": f"{mid}:{status}:{ts}"})
        return out
