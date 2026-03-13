FROM python:3.12-slim
WORKDIR /app

COPY tools/stress/ ./tools/stress/
COPY tests/integration/helpers.py ./tests/integration/helpers.py

ENTRYPOINT ["python", "tools/stress/stress.py"]
CMD ["--list"]
