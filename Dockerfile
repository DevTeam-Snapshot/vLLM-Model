FROM vllm/vllm-openai:v0.15.0

RUN rm -f /usr/local/cuda-12.9/compat/libcuda.so*

EXPOSE 8000

CMD ["--model", "Qwen/Qwen3-0.6B", "--served-model-name", "hotel-copy-llm", "--max-model-len", "2048", "--gpu-memory-utilization", "0.80"]
