FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python -c "from pathlib import Path; p = Path('/app/docker-entrypoint.sh'); p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))"

COPY media/servicios/ /app/media_seed/servicios/

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
