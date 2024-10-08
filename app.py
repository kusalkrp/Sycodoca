from flask import Flask, request, jsonify
from pinecone import Pinecone
from langchain_pinecone import PineconeVectorStore
from src.helper import download_hugging_face_embeddings
from dotenv import load_dotenv
import os
import requests
from langchain_community.embeddings import HuggingFaceEmbeddings

app = Flask(__name__)

load_dotenv()

# Download embedding model
def download_hugging_face_embeddings():
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return embeddings

PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')
PINECONE_API_ENV = os.environ.get('PINECONE_API_ENV')
HUGGINGFACE_API_KEY = os.environ.get('HUGGINGFACE_API_KEY')

embeddings = download_hugging_face_embeddings()

pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_API_ENV)
index_name = "mental-chatbot"
docsearch = PineconeVectorStore.from_existing_index(index_name, embeddings)

API_URL = "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct"
headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}

def query(payload):
    response = requests.post(API_URL, headers=headers, json=payload)
    return response.json()

def truncate_text(text, max_length=1024):
    tokens = text.split()
    return ' '.join(tokens[:max_length])

def split_into_paragraphs(text, sentence_count=3):
    sentences = text.split('. ')
    paragraphs = []
    for i in range(0, len(sentences), sentence_count):
        paragraph = '. '.join(sentences[i:i+sentence_count])
        if paragraph:
            paragraphs.append(paragraph.strip())
    return '\n\n'.join(paragraphs)

class CustomRetrievalQA:
    def __init__(self, retriever, api_url, headers):
        self.retriever = retriever
        self.api_url = api_url
        self.headers = headers
    
    def generate_response(self, user_input):
        retrieved_docs = self.retriever.get_relevant_documents(user_input)
        context = " ".join([doc.page_content for doc in retrieved_docs])
        prompt = f"""Based on the context provided below and the user's answers, generate a comprehensive response that addresses the user's mental health concerns. The response should be between 100 and 150 words, and formatted into 2 or 3 paragraphs. Summarize the context and provide an ultimate conclusion about the potential mental health issues the user might be facing.

Context:
{context}

User's Answers:
{user_input}

Response:"""
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 512,
                "temperature": 0.7
            }
        }
        result = query(payload)
        print(f"Query result: {result}")  # Debugging: Print the query result
        
        generated_text = ""
        if result:
            if isinstance(result, list) and len(result) > 0:
                generated_text = result[0].get("generated_text", "")
            else:
                print("Unexpected result format: ", result)
        else:
            print("No result returned from query")

        response_start = generated_text.find("Response:") + len("Response:")
        response_text = generated_text[response_start:].strip()
        response_text = truncate_text(response_text, max_length=512)
        response_paragraphs = response_text.split('\n')
        
        if len(response_paragraphs) == 1:
            response_paragraphs = self.format_into_paragraphs(response_text)
        
        return "\n\n".join(response_paragraphs)

    def format_into_paragraphs(self, text):
        sentences = text.split('. ')
        paragraphs = []
        current_paragraph = ""
        
        for sentence in sentences:
            if len(current_paragraph) + len(sentence) + 1 > 150:
                paragraphs.append(current_paragraph)
                current_paragraph = sentence + "."
            else:
                if current_paragraph:
                    current_paragraph += " " + sentence + "."
                else:
                    current_paragraph = sentence + "."
        
        if current_paragraph:
            paragraphs.append(current_paragraph)
        
        return paragraphs[:3]

retriever = docsearch.as_retriever(search_kwargs={'k': 2})
custom_qa = CustomRetrievalQA(retriever=retriever, api_url=API_URL, headers=headers)

@app.route("/get", methods=["POST"])
def chat():
    user_answers = request.json.get("answers")
    response = generate_response(user_answers)
    return jsonify({"response": response})

def generate_response(user_answers):
    user_input = " ".join(user_answers)
    user_input = truncate_text(user_input, max_length=512)
    result = custom_qa.generate_response(user_input)
    return truncate_text(result, max_length=512)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080, debug=True)
