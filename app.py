iimport os
import re
import json
import base64
import tempfile
import subprocess
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

@app.route("/")
def home():
    return Response("<!DOCTYPE html><html><head><meta charset='UTF-8'><title>YouTube Analyzer</title></head><body><h1>Server is working!</h1></body></html>", mimetype="text/html")

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
