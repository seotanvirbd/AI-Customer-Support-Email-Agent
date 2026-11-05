# %% Setup: make `app` importable from a script, a terminal, or Jupyter Interactive
import os
import sys
from pathlib import Path


def find_project_root() -> Path:
    """Walk up from this file (or the current folder in Jupyter) to the folder with pyproject.toml."""
    start = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    for folder in [start, *start.parents]:
        if (folder / "pyproject.toml").exists():
            return folder
    raise RuntimeError("Could not find the project root (no pyproject.toml found)")


ROOT = find_project_root()
os.chdir(ROOT)  # so .env and relative paths resolve the same way as in the app
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Jupyter already runs an event loop, and the agents' run_sync() needs to start one.
# nest_asyncio lets them share it. Plain `python` runs skip this.
import asyncio

try:
    asyncio.get_running_loop()
    import nest_asyncio

    nest_asyncio.apply()
except RuntimeError:
    pass

# %% Imports from the app
from pydantic import BaseModel

import app.ai.decide as decide_module
from app.ai.rules import resolve_issue
from app.ai.schemas import AgentReply, Classification, Decision

# %% Your input: edit these and run the cells below
SENDER = "jane.doe@example.com"
SUBJECT = "Missing screws"
QUESTION = """Hi,
my HP-S3 bookcase arrived without the hardware kit. Order number 112-4567890.
Thanks, Jane"""
HAS_ATTACHMENTS = False


# %% Pipeline: runs the real decide(), and records what each model returns
class PipelineTrace(BaseModel):
    thread: str
    classification: Classification | None = None
    agent_reply: AgentReply | None = None
    next_step: str | None = None
    decision: Decision


def build_thread(sender: str, subject: str, question: str) -> str:
    """Same text format as app.gmail.format_thread, for a thread with one customer message."""
    return f"Subject: {subject}\n\nCustomer ({sender}):\n{question.strip()}"


def run_pipeline(question: str, subject: str = "Question", sender: str = SENDER,
                 has_attachments: bool = False) -> PipelineTrace:
    """Send one question through the AI steps. Reads the knowledge base, sends no email."""
    thread = build_thread(sender, subject, question)
    captured = {}

    def record(name, fn):
        def wrapper(*args, **kwargs):
            captured[name] = fn(*args, **kwargs)
            return captured[name]
        return wrapper

    original_classify, original_write_reply = decide_module.classify, decide_module.write_reply
    decide_module.classify = record("classification", original_classify)
    decide_module.write_reply = record("agent_reply", original_write_reply)
    try:
        decision = decide_module.decide(thread, has_attachments)
    finally:
        decide_module.classify, decide_module.write_reply = original_classify, original_write_reply

    agent_reply = captured.get("agent_reply")
    return PipelineTrace(
        thread=thread,
        classification=captured.get("classification"),
        agent_reply=agent_reply,
        next_step=resolve_issue(agent_reply.issue) if agent_reply and agent_reply.issue else None,
        decision=decision,
    )


def show(trace: PipelineTrace) -> None:
    def section(title: str, model: BaseModel | str | None) -> None:
        print(f"\n=== {title} ===")
        if model is None:
            print("(not run)")
        elif isinstance(model, BaseModel):
            print(model.model_dump_json(indent=2))
        else:
            print(model)

    section("1. Input thread", trace.thread)
    section("2. Classification (classifier model)", trace.classification)
    section("3. AgentReply (support agent model)", trace.agent_reply)
    section("4. Next step (app.ai.rules)", trace.next_step)
    section("5. Decision (final result, what would be sent)", trace.decision)


# %% Run it
trace = run_pipeline(QUESTION, SUBJECT, SENDER, HAS_ATTACHMENTS)
show(trace)

# %% Inspect the models directly (handy in Jupyter: just evaluate these)
trace.classification
# %%
trace.agent_reply
# %%
trace.decision
