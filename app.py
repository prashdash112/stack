from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import openai
from openai import OpenAI

app = Flask(__name__)
CORS(app)
openai.api_key = os.getenv("OPENAI_API_KEY")  # Set in environment

@app.route('/')
def home():
    return render_template('index_claude.html')

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    prompt_decorator = 'Important: Just give answer, no unnecessary info. Only add the topic as heading. ' \
    'Generate a creative flashcard that can be shared over social media.'
    prompt = prompt + prompt_decorator
    if not prompt:
        return jsonify({'error': 'Prompt is required.'}), 400

    client = OpenAI(organization=os.environ["GPT_ORG"],
                    project=os.environ["GPT_PROJECT"],
                    api_key = os.environ["GPT_APIKEY"])
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Specify the GPT-4o Mini model
            messages=[
                {"role": "user", "content": prompt} 
            ],
            max_tokens=2000,       # Adjust based on your requirements
            temperature=0.7,      # Controls randomness
            top_p=1.0,            # Controls diversity of the output
            n=1                   # Number of responses to generate
        )
        
        text = response.choices[0].message.content.strip()
        return jsonify({ 'result': text })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", debug=True, port=8000)