"""
audit_agent.py — A tool-calling agent that investigates a Kubernetes audit log
in plain English, using a local Ollama model (qwen2.5:7b).

Flow per question:
  1. Show the model the question and the list of available tools.
  2. Model replies with ONE tool choice as JSON: {"tool": "...", "arg": "..."}.
  3. We run that tool locally, then feed its output back to the model.
  4. Model writes a final plain-English answer grounded in the tool output.

This two-step (choose tool -> answer from result) is the same pattern as the
Lab 2 CloudWatch agent. The reliability lever here is the tool DESCRIPTIONS and
the strict JSON contract, not the model size — the Lab 2 lesson restated.
"""

import json
import sys
import urllib.request

import audit_tools as tools

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:7b"


def _chat(messages, force_json=False):
    """Send a chat request to the local Ollama server and return the reply text."""
    payload = {"model": MODEL, "messages": messages, "stream": False}
    if force_json:
        payload["format"] = "json"  # Ollama constrains output to valid JSON
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return body["message"]["content"]


def _tool_catalog():
    """Format the tool list for the model's system prompt."""
    lines = []
    for name, meta in tools.TOOLS.items():
        arg_note = " (requires 'arg')" if meta["takes_arg"] else " (no arg needed)"
        lines.append(f'- {name}{arg_note}: {meta["description"]}')
    return "\n".join(lines)


def choose_tool(question):
    """Ask the model which single tool to call. Returns (tool_name, arg)."""
    system = (
        "You are a Kubernetes security audit assistant. Given a question, choose "
        "exactly ONE tool to answer it. Reply ONLY with JSON of the form "
        '{"tool": "<tool_name>", "arg": "<string or empty>"}. '
        "Available tools:\n" + _tool_catalog()
    )
    reply = _chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": question}],
        force_json=True,
    )
    try:
        choice = json.loads(reply)
        return choice.get("tool", ""), choice.get("arg", "")
    except json.JSONDecodeError:
        return "", ""


def answer(question):
    """Full loop: choose a tool, run it, then explain the result in plain English."""
    tool_name, arg = choose_tool(question)

    if tool_name not in tools.TOOLS:
        return f"[agent] Could not map that question to a known tool (got: {tool_name!r})."

    meta = tools.TOOLS[tool_name]
    tool_output = meta["fn"](arg) if meta["takes_arg"] else meta["fn"]()

    print(f"  [tool chosen: {tool_name}{f' arg={arg!r}' if arg else ''}]")

    system = (
        "You are a Kubernetes security audit assistant. Answer the user's question "
        "using ONLY the tool output provided. Be concise and specific. If the tool "
        "output shows denied requests or attacks, state clearly what was blocked and why. "
        "Do not invent details not present in the output."
    )
    final = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question: {question}\n\nTool output:\n{tool_output}"},
    ])
    return final


def main():
    print("Kubernetes Audit Log Investigation Agent (local qwen2.5:7b)")
    print("Ask about denied requests, secret access, specific pods, or a summary.")
    print("Type 'quit' to exit.\n")

    # Allow a one-shot question from the command line: python3 audit_agent.py "who was denied?"
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(f"> {q}")
        print(answer(q))
        return

    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in {"quit", "exit"}:
            break
        if not q:
            continue
        print(answer(q))
        print()


if __name__ == "__main__":
    main()
