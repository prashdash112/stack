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
    # return render_template('index_claude.html')
    return render_template('geniuspost_homepage.html')

@app.route("/geniuspost") 
def geniuspost():
    return render_template("index_claude.html")

@app.route("/pricing")
def pricing():
    return render_template('pricing.html') 

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


################################ Using  wkhtmltopdf to eliminate page breaking ###################################
# import os
# import subprocess
# import tempfile
# from flask import Flask, render_template, request, jsonify, send_file, abort
# from flask_cors import CORS
# import openai
# from openai import OpenAI

# app = Flask(__name__)
# CORS(app)
# openai.api_key = os.getenv("OPENAI_API_KEY")  # Make sure this is set in your env

# @app.route('/')
# def home():
#     return render_template('geniuspost_homepage.html')

# @app.route("/geniuspost")
# def geniuspost():
#     return render_template("index_claude.html")

# @app.route('/generate', methods=['POST'])
# def generate():
#     data = request.json or {}
#     prompt = data.get('prompt', '').strip()
#     prompt_decorator = (
#         'Important: Just give answer, no unnecessary info. '
#         'Only add the topic as heading. Generate a creative flashcard that can be shared over social media.'
#     )
#     prompt = prompt + prompt_decorator
#     if not prompt:
#         return jsonify({'error': 'Prompt is required.'}), 400

#     client = OpenAI(
#         organization=os.environ.get("GPT_ORG"),
#         project=os.environ.get("GPT_PROJECT"),
#         api_key=os.environ.get("GPT_APIKEY")
#     )
#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=[{"role": "user", "content": prompt}],
#             max_tokens=2000,
#             temperature=0.7,
#             top_p=1.0,
#             n=1
#         )
#         text = response.choices[0].message.content.strip()
#         return jsonify({'result': text})
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @app.route('/generate-pdf', methods=['POST'])
# def generate_pdf():
#     data = request.get_json()
#     if not data or 'html' not in data:
#         return abort(400, description="Missing 'html' field in JSON body.")

#     html_string = data['html']

#     # 1) Write HTML to a temporary file
#     tmp_html = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
#     tmp_html.write(html_string.encode('utf-8'))
#     tmp_html.flush()

#     # 2) Create a temp file for PDF output
#     tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
#     tmp_pdf.close()

#     try:
#         # 3) Call wkhtmltopdf (with 20px margins, A4)
#         subprocess.check_call([
#             "wkhtmltopdf",
#             "--page-size", "A4",
#             "--margin-top", "8",
#             "--margin-bottom", "8",
#             "--margin-left", "8",
#             "--margin-right", "8",
#             tmp_html.name,
#             tmp_pdf.name
#         ])
#         # 4) Send back the generated PDF
#         return send_file(
#             tmp_pdf.name,
#             mimetype='application/pdf',
#             as_attachment=True,
#             download_name='linkedin-post.pdf'
#         )
#     except subprocess.CalledProcessError as e:
#         return abort(500, description=f"wkhtmltopdf failed: {e}")
#     finally:
#         # 5) Clean up temporary HTML
#         try:
#             os.unlink(tmp_html.name)
#         except:
#             pass
#         # (We leave tmp_pdf in place until after send_file; Flask will cleanup afterward)
#         pass

# if __name__ == '__main__':
#     app.run(host="127.0.0.1", debug=True, port=8000)

