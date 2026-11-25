FROM python:3.13-slim
WORKDIR /app
COPY server/ /app/server/
ENV SAFEVAULT_DATA=/data SAFEVAULT_HOST=0.0.0.0 SAFEVAULT_PORT=8080 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
WORKDIR /app/server
CMD ["python", "-m", "safevault_server"]
