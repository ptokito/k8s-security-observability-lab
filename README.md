# k8s-security-observability-lab

An ephemeral Kubernetes security lab that demonstrates a single uncomfortable
truth: **a cluster can report perfectly healthy while actively blocking attacks,
and traditional monitoring will show you none of it.**

Node Ready. Pods Running. Dashboards green. Meanwhile the admission controller
just rejected two privileged pods, RBAC just denied a secrets read, and the only
place any of it was recorded was the API server audit log. This lab builds that
scenario end to end on real infrastructure, then puts a local AI agent to work
investigating the audit log in plain English.

It extends a thesis I have been developing across earlier labs (most failure and
attack signals are invisible to latency, status codes, and error rates) from
LLM pipelines into Kubernetes security.

---

## The three findings

Everything below was discovered live while running the lab, not scripted in
advance. They are the point of the project.

### 1. Controls block attacks while the health view stays green

Three deliberate attacks were run against the cluster: a privileged pod, a
default root pod, and a scoped service account attempting to read Secrets. All
three were blocked (two by Pod Security Admission enforcing the restricted
standard, one by RBAC). Immediately afterward, `kubectl get nodes` and
`kubectl get pods` reported everything Ready and Running with no indication
anything hostile had occurred. The complete forensic record existed only in the
audit log. This is the core observability gap: the controls worked, and the
health signals told you nothing about it.

### 2. Injected attacks hide inside routine control-plane noise

When the AI agent was asked "what requests were denied," it correctly returned
denied requests, but the two injected attacks were crowded out of the top of the
list by roughly seven routine system denials: failed lease lookups, requests to
non-existent namespaces, a 403 on `/readyz` from `system:k3s-controller`, and
missing cluster roles. These are k3s control-plane components generating normal
denials during operation. The real security events were buried in benign ones.
This is the signal-to-noise problem at the heart of security observability, and
it is a sharper version of the green-span thesis: it is not only that bad things
look green, it is that when they are logged, they drown in ordinary traffic.

### 3. The agent's tool output was accurate, but its language layer added an unsupported claim

Tracing the attack pods by name returned an accurate result, but the model's
final plain-English summary asserted the pods were blocked "because they were
initiated by `system:admin` attempting to use elevated privileges
inappropriately." That is wrong. The requests were blocked by the Pod Security
admission controller for violating the restricted standard, not because of the
caller's identity. In fact `system:admin` was authorized by RBAC; admission
rejected the request at a later stage. The tool told the truth; the LLM layer
introduced a subtle causal error a casual reader would not catch. This is
exactly the kind of failure AI observability exists to instrument, and it maps
directly to the green-span idea: the underlying data was sound, the AI-generated
narrative on top of it was not.

---

## Architecture

| Layer | Choice | KCSA domain touched |
|-------|--------|---------------------|
| Infrastructure | Terraform provisioning a single EC2 spot instance running k3s, with API server audit logging enabled from boot | Cloud Provider and Infrastructure Security |
| Security controls | Pod Security Admission (restricted), least-privilege RBAC service account, default-deny NetworkPolicy | Kubernetes Security Fundamentals |
| Supply chain | GitHub Actions pipeline: build, Trivy scan gate (fails on fixable CRITICAL/HIGH), push to GHCR only on pass | Platform Security, Supply Chain Security |
| Observability | Kubernetes audit policy recording secrets, configmaps, serviceaccounts, and RBAC activity | Platform Security, Observability |
| AI investigation | Local tool-calling agent (Ollama qwen2.5:7b) querying the exported audit log in plain English | (portfolio extension) |

KCSA is the Kubernetes and Cloud Native Security Associate certification. RBAC is
Role Based Access Control. GHCR is the GitHub Container Registry. Trivy is an
open source vulnerability scanner. Ollama is a local model server.

The whole environment is designed to stand up with one `terraform apply` and
tear down with one `terraform destroy`. A full working session costs roughly
15 to 20 cents.

---

## How it works

### Ephemeral infrastructure (`terraform/`)

Terraform provisions a spot instance with a firewall locked to a single IP, and
a boot script that writes an audit policy and installs k3s with the audit log
wired into the API server before the server starts. The audit policy records
metadata on secrets, configmaps, and service accounts, and full request/response
detail on RBAC objects. That log is the raw material for the whole observability
story.

### Security controls (applied in-cluster)

- A namespace labelled to enforce the restricted Pod Security Standard, so
  non-compliant pods are rejected at creation.
- A service account scoped to read pods in one namespace and nothing else,
  verified with four `kubectl auth can-i` checks (one yes, three no).
- A default-deny ingress NetworkPolicy.

### Supply chain gate (`.github/workflows/`)

On every push to main, the pipeline builds the demo image, scans it with Trivy,
and fails if any fixable CRITICAL or HIGH vulnerability is present. The image is
pushed to GHCR only if the scan passes, so the scan sits between build and push
as an actual gate rather than a report. The application image uses a pinned slim
base and a non-root user so it can pass the restricted admission standard.

### AI investigation agent (`agent/`)

`audit_tools.py` exposes four query functions over the audit log
(`find_denied_requests`, `who_accessed_secrets`, `summarize_activity`,
`find_by_name`), each returning plain text. `audit_agent.py` shows a local
qwen2.5:7b model the question plus the tool descriptions; the model replies with
a single JSON tool choice; the tool runs locally; the model then writes a
grounded answer from the tool output. Across query types the model selected the
correct tool on the first attempt, which is a reasonable reliability result for a
local 7B model and the reason tool descriptions, not model size, are the main
lever here.

---

## Running it yourself

Prerequisites: an AWS account with EC2 permissions, Terraform, the AWS CLI, an
SSH key, and (for the agent) Ollama serving `qwen2.5:7b`.

```bash
# 1. Stand up the cluster (substitute your public IP)
cd terraform
terraform init
terraform apply -var="my_ip=YOUR.PUBLIC.IP/32" -auto-approve

# 2. SSH in using the printed ssh_command, then apply controls and deploy
#    (manifests and commands are in the walkthrough)

# 3. Export the audit log to your machine and run the agent
cd ../agent
python3 audit_agent.py "What requests were denied and why?"

# 4. Tear it all down
cd ../terraform
terraform destroy -var="my_ip=YOUR.PUBLIC.IP/32" -auto-approve
```

---

## Notes on scope and honesty

The Terraform and k3s configuration were adapted and run rather than authored
from scratch; the security findings, the audit policy design, and the agent tool
set are the substance of the work. The EC2 permissions used by the lab IAM user
were granted for the lab window and revoked at teardown, keeping that identity at
least privilege by default. IAM is AWS Identity and Access Management.
