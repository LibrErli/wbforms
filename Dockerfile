FROM python:3.12-alpine
LABEL authors="tholzheim"

WORKDIR /app
COPY . .

RUN python -m pip install --upgrade pip

RUN pip install .
EXPOSE 8000

CMD ["python", "src/wbforms/main.py"]