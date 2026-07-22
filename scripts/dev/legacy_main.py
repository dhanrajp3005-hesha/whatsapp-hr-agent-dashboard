from fastapi import FastAPI
from app.whatsapp import open_whatsapp

app = FastAPI()


@app.get("/")
def home():
    return {"status": "WhatsApp HR Agent Running"}


@app.get("/open-whatsapp")
def launch():
    open_whatsapp()
    return {"status": "WhatsApp opened"}
