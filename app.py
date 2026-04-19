from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import os

app = Flask(__name__)
CORS(app)

# Твоя ссылка на базу
MONGO_URL = "mongodb+srv://admin:MaksimPass2026@cluster0.20wnbqk.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client.padik_db

@app.route('/')
def home():
    return "Server Padik is Online!"

@app.route('/send', methods=['POST'])
def send():
    data = request.json
    db.messages.insert_one(data)
    return jsonify({"status": "ok"}), 200

@app.route('/get', methods=['GET'])
def get_messages():
    msgs = list(db.messages.find({}, {"_id": 0}))
    return jsonify(msgs), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
