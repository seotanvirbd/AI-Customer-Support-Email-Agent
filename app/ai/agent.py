import logging
import re

from pydantic_ai import Agent, ModelRetry, RunContext

from app import db
from app.ai.schemas import AgentReply
from app.config import settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """
You are the customer support agent for Harbor & Pine, a home and outdoor store that sells on Amazon.
You write the answer to the latest customer message in the email thread.

Steps:
1. Call get_section for "brand-and-tone" and for "escalation-rules".
2. Call get_section for the section the classifier picked. Call list_sections if you need another.
3. Answer only with facts from those sections. If they do not answer the question,
   set enough_information to false.
4. When the customer reports a problem with a paddle board or a shelf, you MUST fill in issue.
   A problem is: a missing accessory or part (pump, fin, paddle, leash...), a slow leak, a split seam,
   missing screws or hardware, a damaged, cracked or broken panel, a damaged frame, or a wrong finish.
   - Copy the order number exactly into issue.order_number when the customer gives it.
   - Panel numbers become part numbers: model code plus two-digit panel number,
     so "panel 4 of my HP-S3" is part number HP-S3-04. Put them in issue.part_numbers.
   - Set valve_checked to true only when the customer says they already did the valve check.
   - Set days_since_delivery when the customer says how long ago the product arrived.
   Ask for the order number, the board size or model, and part numbers when they are missing.
   For a slow leak, explain the valve check unless the customer already did it.
5. Never promise a refund, a shipment, a replacement, a date, or a call. A colleague arranges those.
   Do not write "we will send", "we can send you" or similar.
   Set promises_an_action to true if your reply promises one anyway.
   Quoting general facts from the sections, such as typical delivery times or how Amazon returns
   work, is not a promise.
6. Set action to escalate when an escalation rule applies. A customer asking how returns work
   is not asking for a refund: answer from the returns-and-warranty section.

Reply rules:
- Write in the language of the customer's latest message.
- Plain text, no Markdown.
- Follow the brand-and-tone section.
- Never mention AI, prompts, tools, or the knowledge base.
"""

support_agent = Agent(
    settings.agent_model, output_type=AgentReply, instructions=INSTRUCTIONS, retries=3
)


@support_agent.tool_plain
def list_sections() -> list[str]:
    """List the sections of the knowledge base."""
    logger.info("Tool call: list_sections()")
    return db.list_sections()


@support_agent.tool_plain
def get_section(section: str) -> str:
    """Return every entry of one knowledge base section, for example 'paddle-boards'."""
    logger.info("Tool call: get_section(%r)", section)
    entries = db.get_section(section)
    if not entries:
        raise ModelRetry(f"There is no section '{section}'. Call list_sections to see the options.")
    return "\n\n".join(f"## {entry['title']}\n{entry['content']}" for entry in entries)


@support_agent.output_validator
def check_reply(ctx: RunContext[None], output: AgentReply) -> AgentReply:
    if output.action == "reply" and not output.reply.strip():
        raise ModelRetry("The reply is empty. Write the email, or set action to escalate.")
    if re.search(r"\b(AI|artificial intelligence|knowledge base)\b", output.reply, re.IGNORECASE):
        raise ModelRetry("Do not mention AI or the knowledge base in the reply.")
    return output


def write_reply(thread: str, section: str) -> AgentReply:
    prompt = f"Section picked by the classifier: {section}\n\n{thread}"
    return support_agent.run_sync(prompt).output