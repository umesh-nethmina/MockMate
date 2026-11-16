"""Offline stand-in for Claude. Used by the tests and by local dev with USE_FAKE_LLM=true (no API key, no cost)."""

from collections import deque

from app.llm.client import LLMResult, LLMUsage

SAMPLE_QUESTIONS = [
    "Hi, thanks for joining! To start, can you tell me about a project you're proud of?",
    "What was the hardest technical problem in that project, and how did you solve it?",
    "How would you explain the difference between a list and a tuple in Python?",
    "Tell me about a time you disagreed with a teammate. What happened?",
    "How do you make sure your code is correct before you ship it?",
    "What happens, step by step, when a browser requests a web page?",
    "How would you find out why an API endpoint suddenly became slow?",
    "Why do you want this role, and what do you hope to learn in it?",
]


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.queue: deque = deque()  # BaseModel outputs or Exceptions, consumed in order when the type matches
        self.n = 0

    def structured(self, *, agent, prompt, messages, output_model, effort, max_tokens=8000):
        from app.agents.evaluator import AnswerScore, CodeReview, ReportSummary, StarFlags
        from app.agents.interviewer import InterviewerTurn

        self.calls.append({"agent": agent, "prompt": prompt, "messages": messages, "effort": effort})
        usage = LLMUsage(agent=agent, prompt=prompt, model="fake", input_tokens=100, output_tokens=50,
                         latency_ms=5, cost_usd=0.001)
        if self.queue and isinstance(self.queue[0], Exception | output_model):
            item = self.queue.popleft()
            if isinstance(item, Exception):
                raise item
            return LLMResult(item, usage)

        if output_model is InterviewerTurn:
            self.n += 1
            out = InterviewerTurn(decision="next_topic", previous_answer_quality="none" if self.n == 1 else "adequate",
                                  round="technical", topic=f"Topic {self.n}", difficulty="medium",
                                  about_cv_project=False, question=f"Question {self.n}?")
        elif output_model is AnswerScore:
            out = AnswerScore(correctness=8, clarity=6, depth=7,
                              star=StarFlags(situation=True, task=True, action=True, result=False),
                              feedback="Good.", model_answer="Model.")
        elif output_model is ReportSummary:
            out = ReportSummary(strengths=["s"], weaknesses=["w"], summary="Summary.")
        elif output_model is CodeReview:
            out = CodeReview(code_quality=7, efficiency=6, feedback="Readable code.", model_answer="Use a hash map.")
        else:  # pragma: no cover
            raise AssertionError(output_model)
        return LLMResult(out, usage)

    def agents(self) -> list[str]:
        return [c["agent"] for c in self.calls]


class DemoLLM(FakeLLM):
    """FakeLLM with readable text, for clicking through the UI locally."""

    def structured(self, *, agent, prompt, messages, output_model, effort, max_tokens=8000):
        from app.agents.evaluator import AnswerScore, CodeReview, ReportSummary
        from app.agents.interviewer import InterviewerTurn

        result = super().structured(agent=agent, prompt=prompt, messages=messages, output_model=output_model,
                                    effort=effort, max_tokens=max_tokens)
        out = result.output
        if isinstance(out, InterviewerTurn):
            out.question = SAMPLE_QUESTIONS[(self.n - 1) % len(SAMPLE_QUESTIONS)]
            note = str(messages[-1]["content"])
            if "must be about a specific project named in the CV" in note:
                out.question = "Your CV mentions a project - what was your own role in it, and what was the result?"
                out.about_cv_project = True
            out.topic = ["Projects", "Problem solving", "Python basics", "Teamwork", "Testing", "Web basics",
                         "Debugging", "Motivation"][(self.n - 1) % 8]
        elif isinstance(out, AnswerScore):
            words = len(str(messages[-1]["content"]).split("<candidate_answer>")[-1].split())
            base = max(2, min(9, 3 + words // 15))
            out.correctness, out.clarity, out.depth = base, min(10, base + 1), max(1, base - 1)
            out.feedback = "(Demo mode) You answered the question; adding a concrete example would make it stronger."
            out.model_answer = "(Demo mode) A strong answer would state the situation, what you did, and the result."
        elif isinstance(out, CodeReview):
            out.feedback = "(Demo mode) Your code is readable; check the complexity and the edge cases."
            out.model_answer = "(Demo mode) Set ANTHROPIC_API_KEY to get a real review and an optimal solution."
        elif isinstance(out, ReportSummary):
            out.strengths = ["(Demo mode) Clear, direct answers"]
            out.weaknesses = ["(Demo mode) Add specific examples and measurable results"]
            out.summary = "(Demo mode) This report uses placeholder scoring. Set ANTHROPIC_API_KEY for real feedback."
        return result
