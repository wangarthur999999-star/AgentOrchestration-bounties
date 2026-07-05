"""API Docs Generator — 2-agent code-to-OpenAPI pipeline.

Agents:
- Analyzer: Reads source code, extracts API endpoints, parameters, responses
- Writer: Generates OpenAPI/Swagger documentation from analysis

Usage:
    python main.py --file src/api/routes.py
    python main.py --dir src/api/ --output openapi.json
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator
from src.sdk.llm_agent import LLMAgent

ANALYZER_PROMPT = """You are an API architect analyzing source code. Given API route code:
1. List every endpoint: method, path, summary
2. For each endpoint: request parameters (path, query, body), their types and required/optional
3. Response schemas: status codes, response body structure
4. Authentication required per endpoint
5. Any middleware or decorators that modify behavior
Output structured JSON suitable for OpenAPI generation."""

WRITER_PROMPT = """You are a technical writer specializing in API documentation.
Given an API analysis:
1. Generate an OpenAPI 3.0 specification (JSON format preferred)
2. Write a human-readable "Getting Started" section
3. Provide 2-3 curl examples for key endpoints
4. Document authentication flow
5. Note any rate limits, pagination, or error response formats mentioned
Output complete, valid OpenAPI JSON followed by the human-readable guide in Markdown."""


async def main():
    parser = argparse.ArgumentParser(description="AI API Docs Generator (2-agent team)")
    parser.add_argument("--file", help="Path to API source file")
    parser.add_argument("--dir", help="Path to API source directory")
    parser.add_argument("--output", default="", help="Save OpenAPI spec to file")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    code = ""
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            code = f.read()
    elif args.dir:
        import glob
        for py_file in glob.glob(f"{args.dir}/**/*.py", recursive=True):
            with open(py_file, encoding="utf-8") as f:
                code += f"\n// File: {py_file}\n{f.read()}"
    else:
        print("Reading from stdin...")
        code = sys.stdin.read()

    if not code.strip():
        print("Error: No code provided")
        return 1

    analyzer = LLMAgent("analyzer", "API Analyzer", ANALYZER_PROMPT, api_key=api_key)
    writer = LLMAgent("writer", "Docs Writer", WRITER_PROMPT, api_key=api_key)

    agents = {"analyzer": analyzer, "writer": writer}
    strategy = ManagerWorkerStrategy(
        manager_agent_id="writer",
        worker_agent_ids=["analyzer"],
    )

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="api-docs",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": f"Generate API documentation for this code:\n\n```\n{code[:12000]}\n```"},
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    output = result.get("synthesis", "No output")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"API docs saved to {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
