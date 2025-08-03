FROM python:3.9-slim

WORKDIR /DSA-LAB5/rest

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]