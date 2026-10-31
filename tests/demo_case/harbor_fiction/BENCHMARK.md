# Opt-in Harbor AI benchmark

This runs the application's `AskWorker._retrieve` (hybrid search, potentially
falling back to keyword search) followed by `AskWorker._generate`, twice. It
does not exercise the GUI, startup, or examination and does not force a cold
model. The first measurement is cold **only if** the operator established that
state beforehand; the second is merely a warm candidate. Retrieval, generation
and total wall times are reported, with validation time separate from generation.
There is no expected answer or score.

Use a separate Windows machine and a disposable IDFA data directory containing
no real cases. Prepare the fictional image as described in README.md, examine
it, and optionally index it. The harness requires precisely one active evidence
item matching the image SHA-256 and precisely the four root text artifacts with
their expected contents, types, generated ID format and paths, and checks their
indexed passages. Extra entries without text are permitted but never included in
model context; retrieval of one aborts rather than silently filtering it. Extra
text artifacts, removed evidence, and unexpected formatting are rejected; the
script does not edit or delete case data. Validation cannot prove that every other file
or database on the machine is synthetic.

Configure both chat and embeddings as Ollama, and the GUI worker, Ollama and
Qdrant URLs as literal loopback HTTP addresses. Start the services yourself.
The worker's `IDFA_OLLAMA_HOST` is configured in the **worker process**, not
verifiable from the GUI configuration: check that it is loopback too. Block
outbound network access for the worker, Ollama, and benchmark process (for
example using Windows Firewall) and inspect their configurations before running.
Loopback URL checks alone cannot establish the identity or forwarding behavior
of an independently running service. `--confirm-isolated-worker` attests that
you have independently established outbound containment and checked service
settings. The script cannot verify or enforce either and fails without this
attestation. GUI provider checks cannot establish the worker's actual routing or
prevent forwarding by a service. CPU-only execution is **not guaranteed**: Ollama may
use an available GPU; configure and verify your runtime separately.

From the project root, after replacing the ID with the disposable case's numeric
database ID:

```powershell
.venv\Scripts\python.exe tests\demo_case\harbor_fiction\benchmark_ai.py --run --confirm-isolated-worker --case-id 1
```

Without `--run` the script only prints help; it does not access the database or
start a model. The run makes up to two generation requests; embedding requests
may also occur during hybrid retrieval. It does not download models, start or
stop services, or clear caches. Model and service configuration is external.
JSON goes to stdout, including the answer. `supplied_source_ids` identifies
retrieved context. `worker_reported_citations` is the worker's source metadata,
not proof that the answer cited those sources. `answer_literal_supplied_ids`
and `answer_bracket_markers` are literal observations, not a citation parser or
grounding verdict; inspect the answer and compare the fictional source texts
manually. No result or accuracy is assumed. Errors abort or are reported rather
than fabricating a measurement. Do not publish output without reviewing it.
