import time
from dataclasses import dataclass

from pydantic_ai.exceptions import ModelConnectionError, ModelRateLimitError, ModelServerError

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from app.ai.decide import decide
from app.ai.schemas import Decision
from evals.golden_emails import GOLDEN_EMAILS


@dataclass
class SectionMatches(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.section == ctx.expected_output["section"]


@dataclass
class ActionMatches(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.action == ctx.expected_output["action"]


def run_pipeline(email: str) -> Decision:
    # Groq's free tier allows ~7k input tokens per minute, so wait and retry on rate limits
    # and dropped connections instead of failing the case.
    for attempt in range(6):
        try:
            return decide(email)
        except (ModelRateLimitError, ModelConnectionError, ModelServerError):
            if attempt == 5:
                raise
            time.sleep(15 * (attempt + 1))
    raise AssertionError("unreachable")


dataset = Dataset(
    name="golden-emails",
    cases=[
        Case(
            name=case["name"],
            inputs=case["email"],
            expected_output={"section": case["section"], "action": case["action"]},
        )
        for case in GOLDEN_EMAILS
    ],
    evaluators=[SectionMatches(), ActionMatches()],
)

if __name__ == "__main__":
    report = dataset.evaluate_sync(run_pipeline, max_concurrency=1)
    report.print(include_input=False, include_output=True, include_durations=False)