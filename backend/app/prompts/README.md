# Prompts

All agent prompts live here as versioned Markdown files (NFR-17), e.g. `interviewer.v1.md`.
Never inline prompt text in Python code; load it via the prompt loader in `app/llm/`.
When changing a prompt, add a new version file and re-run the evaluator eval set.
