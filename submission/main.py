"""CrewAI starter: a three-agent crew (researcher -> writer -> editor).

Run:  uv run python main.py "your topic here"

CrewAI's big idea: you describe a TEAM of role-playing agents and the TASKS they
own. CrewAI handles passing each task's output to the next agent.
"""
import os
import sys
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

# --- 1. The model --------------------------------------------------------
# CrewAI has no built-in Groq provider, but Groq speaks the OpenAI API, so we
# point CrewAI's OpenAI client at Groq's endpoint. Change GROQ_MODEL in .env
# to swap models without touching this file.
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
llm = LLM(
    model=f"openai/{MODEL}",  # the leading "openai/" only selects the client
    base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0.3,
)


# --- 2. The agents: WHO is on the team ----------------------------

researcher = Agent(
    role="Linux Infrastructure Analyst",
    goal=(
        "Analyze the Linux infrastructure incident described in {topic}. "
        "Identify plausible root causes, supporting evidence, and "
        "diagnostic commands."
    ),
    backstory=(
        "You are an experienced Linux systems engineer specializing in "
        "RHEL, server infrastructure, virtualization, networking, and "
        "production incident troubleshooting. You distinguish facts "
        "from hypotheses and never invent diagnostic results."
    ),
    llm=llm,
    allow_delegation=False,
)

writer = Agent(
    role="Infrastructure Technical Writer",
    goal=(
        "Convert the research findings into a practical troubleshooting "
        "brief for the operations team."
    ),
    backstory=(
        "You write clear technical reports for engineers and operations "
        "managers. You prioritize impact, likely causes, diagnostic "
        "commands, and remediation steps."
    ),
    llm=llm,
    allow_delegation=False,
)

editor = Agent(
    role="Technical Editor",
    goal=(
        "Improve the troubleshooting brief while preserving technical "
        "accuracy and identifying unsupported assumptions."
    ),
    backstory=(
        "You specialize in reviewing Linux operations documentation. "
        "You eliminate ambiguity, distinguish symptoms from root causes, "
        "and flag commands that could disrupt production."
    ),
    llm=llm,
    allow_delegation=False,
)

checker = Agent(
    role="Infrastructure Quality Reviewer",
    goal=(
        "Review the final troubleshooting brief for technical consistency, "
        "completeness, safety, and actionable diagnostic steps."
    ),
    backstory=(
        "You are a senior infrastructure engineer reviewing incident "
        "reports before they are used by an operations team. You verify "
        "that commands match the stated problem, flag destructive actions, "
        "and identify what evidence is still needed."
    ),
    llm=llm,
    allow_delegation=False,
)

# --- 3. The tasks: WHAT each agent owns ----------------------------


research_task = Task(
    description="Analyze {topic}. List 3 key facts and 2 open questions.",
    expected_output="3 key facts and 2 open questions.",
    agent=researcher,
)

writing_task = Task(
    description="Write a short explanation of {topic} using the research.",
    expected_output="A concise explanation.",
    agent=writer,
)

editing_task = Task(
    description="Improve the explanation and flag unsupported claims.",
    expected_output="An edited explanation.",
    agent=editor,
)

checking_task = Task(
    description="Check the explanation for errors and missing information.",
    expected_output="A concise, checked final explanation.",
    agent=checker,
)

# --- 4. The crew: HOW they work together ---------------------------

crew = Crew(
    agents=[researcher, writer, editor, checker],
    tasks=[
        research_task,
        writing_task,
        editing_task,
        checking_task,
    ],
    process=Process.sequential,
    verbose=True,
)


if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]) or "how small teams can use AI agents in data science"
    result = crew.kickoff(inputs={"topic": topic})

    out = Path("output")
    out.mkdir(exist_ok=True)
    (out / "explainer.md").write_text(result.raw, encoding="utf-8")
    print("\n=== FINAL OUTPUT (also saved to output/explainer.md) ===\n")
    print(result.raw)
