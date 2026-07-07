import logging

from fastapi import FastAPI, HTTPException, Header
from .handler import handle_prediction

logger = logging.getLogger(__name__)

app = FastAPI()


@app.post("/api/match-predict")
@app.post("/api/match-predict/")
def infer(data: dict, authorization: str = Header(None)):
    status, body = handle_prediction(data, authorization)
    if status != 200:
        raise HTTPException(status, body)
    return body
