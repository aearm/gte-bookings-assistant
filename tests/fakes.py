"""A stand-in for the Claude API: answers come from a script, and every request is recorded."""
import json
from types import SimpleNamespace


def text_response(data: dict):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(data))])


def tool_response(*calls):
    blocks = [SimpleNamespace(type="tool_use", id=f"call_{i}", name=name, input=args)
              for i, (name, args) in enumerate(calls)]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


class FakeClaude:
    """Install with monkeypatch.setattr(llm, "_create", fake). Each response is a dict (JSON answer)
    or a list of (tool name, input) calls; a callable gets the request and returns either."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, **kwargs):
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("Claude was asked more often than the test expected")
        nxt = self.responses.pop(0)
        if callable(nxt):
            nxt = nxt(kwargs)
        return tool_response(*nxt) if isinstance(nxt, list) else text_response(nxt)

    def system_text(self, i: int = 0) -> str:
        return "".join(b["text"] for b in self.requests[i]["system"])

    def user_text(self, i: int = 0) -> str:
        content = self.requests[i]["messages"][0]["content"]
        return content if isinstance(content, str) else json.dumps(content)


def plan(steps, combine_sql="", understanding="Understood", chart_request="", **extra):
    return {"understanding": understanding, "needs_clarification": False, "clarifying_question": "",
            "options": [], "reuse_previous": False, "steps": steps, "combine_sql": combine_sql,
            "explanation": "The numbers asked for.", "chart_request": chart_request, **extra}


def chart(chart_type="bar", x="", y=None, color="", custom_chart="", summary="Summary."):
    return {"chart_type": chart_type, "x": x, "y": y or [], "color": color, "custom_chart": custom_chart,
            "title": "Title", "summary": summary}
