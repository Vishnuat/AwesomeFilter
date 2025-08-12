# Use a modern, slim, and supported version of Python
FROM python:3.12-slim

WORKDIR /TamilanBotsZ

COPY requirements.txt ./

RUN pip install -r requirements.txt

# Copy the rest of your application code
COPY . .

CMD ["python3", "bot.py"]
