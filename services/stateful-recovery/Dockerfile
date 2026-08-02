FROM python:3.13-alpine@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0

WORKDIR /app
COPY recovery_fixture.py /app/recovery_fixture.py

EXPOSE 8080
ENTRYPOINT ["python3", "/app/recovery_fixture.py"]
CMD ["serve"]
