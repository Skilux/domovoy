# Python 3.11 matches apify/.venv (3.11.14) and the apify/actor-python:3.11 tag on Docker Hub.
FROM apify/actor-python:3.11

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

CMD ["python3", "-m", "domovoy"]
