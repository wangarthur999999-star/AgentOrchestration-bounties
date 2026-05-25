"""Test Generator — Generate comprehensive pytest test suites from source code.

Usage:
    python main.py --file src/my_module.py
    python main.py --dir src/
"""

import argparse
import asyncio
import os
import sys

from openai import AsyncOpenAI

TEST_GENERATOR_PROMPT = """You are a senior test engineer. Generate a COMPLETE pytest test file
for the given source code. Include:

1. Tests for every function/method
2. Happy path tests
3. Edge cases (empty input, None, boundary values)
4. Error cases (invalid input, exceptions)
5. Mock external dependencies properly
6. Use descriptive test names with underscores

Output ONLY the test file content as valid Python code. Include necessary imports.
Use pytest fixtures where appropriate. Arrange-Act-Assert pattern.

IMPORTANT: Only output the test code, no explanations."""


class TestGenerator:
    def __init__(self, api_key: str = "", base_url: str = "https://api.deepseek.com/v1"):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)

    async def generate_tests(self, source_code: str, module_name: str = "module") -> str:
        response = await self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": TEST_GENERATOR_PROMPT},
                {"role": "user", "content": f"Generate pytest tests for this module ({module_name}):\n\n```python\n{source_code[:12000]}\n```"},
            ],
            max_tokens=4096,
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return content

    async def generate_for_directory(self, dir_path: str) -> dict[str, str]:
        """Generate tests for all .py files in a directory."""
        results = {}
        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.endswith(".py") and not file.startswith("test_"):
                    path = os.path.join(root, file)
                    with open(path, encoding="utf-8") as f:
                        source = f.read()
                    test_code = await self.generate_tests(source, file.replace(".py", ""))
                    test_filename = f"test_{file}"
                    results[test_filename] = test_code
        return results

    def save_tests(self, tests: dict[str, str], output_dir: str = "tests") -> None:
        os.makedirs(output_dir, exist_ok=True)
        for filename, code in tests.items():
            path = os.path.join(output_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"  Generated: {path}")


async def main():
    parser = argparse.ArgumentParser(description="AI Test Generator")
    parser.add_argument("--file", help="Source file to generate tests for")
    parser.add_argument("--dir", help="Directory to generate tests for all .py files")
    parser.add_argument("--output", "-o", default="tests", help="Output directory (default: tests/)")
    args = parser.parse_args()

    generator = TestGenerator()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            source = f.read()
        module_name = os.path.basename(args.file).replace(".py", "")
        print(f"Generating tests for {args.file}...")
        test_code = await generator.generate_tests(source, module_name)
        test_filename = f"test_{os.path.basename(args.file)}"
        generator.save_tests({test_filename: test_code}, args.output)
        print(f"Done! Test file: {args.output}/{test_filename}")

    elif args.dir:
        print(f"Generating tests for all .py files in {args.dir}...")
        tests = await generator.generate_for_directory(args.dir)
        generator.save_tests(tests, args.output)
        print(f"Done! Generated {len(tests)} test files.")

    else:
        print("Reading from stdin...")
        source = sys.stdin.read()
        if source.strip():
            test_code = await generator.generate_tests(source)
            print(test_code)
        else:
            print("Error: No source code provided")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
