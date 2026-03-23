import os
from flask import Flask, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return Response("<h1>Server is working!</h1>", mimetype="text/html")

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
