FROM vllm/vllm-openai:latest

EXPOSE 8000

CMD [
  "--model", "Qwen/Qwen3-0.6B",
  "--served-model-name", "hotel-copy-llm",
  "--max-model-len", "2048",
  "--gpu-memory-utilization", "0.80"
]