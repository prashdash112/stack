from flask import Flask, render_template, request, jsonify, redirect, url_for,send_file
import requests
from flask_cors import CORS
import os
import openai
from openai import OpenAI
import anthropic
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
import tempfile
import base64
from io import BytesIO
import markdown
import time



app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
# openai.api_key = os.getenv("OPENAI_API_KEY")  # Set in environment
app.secret_key = os.environ['SECRET_KEY']
# ─── Database Configuration ────────────────────────────
# Render will inject DATABASE_URL into your environment
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ["DATABASE_URL"] 
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Setup Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

#### Added Db model 
class User(db.Model, UserMixin):
    id = db.Column(db.String(50), primary_key=True)  # Use Google user ID as primary key
    name = db.Column(db.String(150))
    email = db.Column(db.String(150), unique=True)
    avatar_url = db.Column(db.String(500))  
    def __repr__(self):
        return f"<User id={self.id} name={self.name} email={self.email}>"
############ USer stats log #########################

class UserMetrics(db.Model):
    __tablename__ = "user_metrics"

    user_id            = db.Column(db.String(50), db.ForeignKey("user.id"), primary_key=True)
    username           = db.Column(db.String(150), nullable=False)
    email              = db.Column(db.String(150), nullable=False)
    login_count        = db.Column(db.Integer, default=0, nullable=False)
    generate_count     = db.Column(db.Integer, default=0, nullable=False)
    infographic_count  = db.Column(db.Integer, default=0, nullable=False)
    export_pdf_count   = db.Column(db.Integer, default=0, nullable=False)
    insert_image_count = db.Column(db.Integer, default=0, nullable=False)
    regenerate_count   = db.Column(db.Integer, default=0, nullable=False)
    clear_count        = db.Column(db.Integer, default=0, nullable=False)
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="metrics", uselist=False)


    def touch(self, action):
        """Increment the right counter (even if it was None) and update timestamp."""
        attr = f"{action}_count"
        current = getattr(self, attr) or 0
        setattr(self, attr, current + 1)
        self.updated_at = datetime.now(timezone.utc)
########################################################

# Create the database tables if they don't exist
with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    print("USER ID", User.query.get(user_id))
    return User.query.get(user_id) 
    
# Google OAuth configuration – store these in your environment variables
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
# Set your redirect URI as registered in the Google console
REDIRECT_URI = os.environ.get("REDIRECT_URI")

# to alert at startup whether a var is missing. 
for var in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','REDIRECT_URI','SECRET_KEY'):
    if not os.environ.get(var):
        raise RuntimeError(f"Missing required env var: {var}")

@app.route("/login")
def login():
    # grab the “next” page (default to /geniuspost)
    next_page = request.args.get("next", url_for("geniuspost"))

    # include that as state, so Google will echo it back
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        "response_type=code"
        f"&client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid+email+profile"
        f"&state={next_page}"
    )
    return redirect(google_auth_url)

@app.route("/authorize")
def authorize():
    code = request.args.get("code")
    if not code:
        return "Error: No code provided", 400
    # Google will return us the original state
    next_page = request.args.get("state", url_for("geniuspost"))
    # Exchange authorization code for tokens 
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    print("Token data:", token_data)
    token_response = requests.post(token_url, data=token_data)
    token_json = token_response.json()
    print("Token response:", token_json)
    access_token = token_json.get("access_token")
    if not access_token:
        # Log error details if access token is missing
        return "Access token not retrieved. Check token response.", 400 
    
    # Fetch user info from Google
    user_info_url = "https://openidconnect.googleapis.com/v1/userinfo" #"https://www.googleapis.com/oauth2/v2/userinfo"
    headers = {"Authorization": f"Bearer {access_token}"}
    user_info_response = requests.get(user_info_url, headers=headers)
    print("User info response:", user_info_response.json())
    
    if user_info_response.status_code == 200:
        user_data = user_info_response.json()
        # Check if user already exists in the database
        user = User.query.get(user_data["sub"])
        print("User validated:", user)
        if not user:
            user = User(
                id=user_data["sub"],
                name=user_data["name"],
                email=user_data["email"],
                avatar_url=user_data.get("picture")
            )
            db.session.add(user)
            db.session.commit()
        print("\n\nUser Record:\n\n",user )
        # login_user(user)
        # return redirect(url_for("home"))
        login_user(user)
        # fetch or create the metrics row
        metrics = UserMetrics.query.get(user.id)
        if not metrics:
            metrics = UserMetrics(
                user_id=user.id,
                username=user.name,
                email=user.email
            )
            db.session.add(metrics)

        metrics.touch("login")
        db.session.commit()

        # finally send them on to whatever they originally wanted
        return redirect(next_page)
    else:
        return "User information could not be retrieved", 400  

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route('/')
def home():
    # return render_template('index_claude.html')
    return render_template('geniuspost_homepage.html',current_user=current_user)

@app.before_request
def require_login_for_genius():
    # if they hit /geniuspost and aren’t authed, send to login
    if request.endpoint == "geniuspost" and not current_user.is_authenticated:
        return redirect(url_for("login", next=url_for("geniuspost")))

@app.route("/geniuspost") 
def geniuspost():
    return render_template("index_claude.html", current_user=current_user)

@app.route("/pricing")
def pricing():
    return render_template('pricing.html') 

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    prompt_decorator = 'Important: 1) Dont give unnecessary information.' 
    prompt = prompt + prompt_decorator
    if not prompt:
        return jsonify({'error': 'Prompt is required.'}), 400

    # client = OpenAI(organization=os.environ["GPT_ORG"],
    #                 project=os.environ["GPT_PROJECT"],
    #                 api_key = os.environ["GPT_APIKEY"])
    # try:
    #     response = client.chat.completions.create(
    #         model="gpt-4o-mini",  # Specify the GPT-4o Mini model
    #         messages=[
    #             {"role": "user", "content": prompt} 
    #         ],
    #         max_tokens=2000,       # Adjust based on your requirements
    #         temperature=0.7,      # Controls randomness
    #         top_p=1.0,            # Controls diversity of the output
    #         n=1                   # Number of responses to generate
    #     )
        
    #     text = response.choices[0].message.content.strip()

    client = anthropic.Anthropic(
        api_key=os.environ["CLAUDE_APIKEY"]
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            temperature=1,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        text = response.content[0].text.strip()
        return jsonify({ 'result': text })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/markdown_editor.html')
def markdown_editor():
    return render_template('markdown_editor.html')

@app.route("/carousel_template.html")
def carousel_template():
    return render_template("carousel_template.html")


@app.route("/track_action", methods=["POST"])
@login_required
def track_action():
    data   = request.get_json() or {}
    action = data.get("action")
    # map incoming action strings to model suffixes
    allowed = {
      "generate_ai_content": "generate",
      "infographic":         "infographic",
      "export_pdf":          "export_pdf",
      "insert_image":        "insert_image",
      "regenerate":          "regenerate",
      "clear":               "clear"
    }
    if action not in allowed:
        return jsonify({"error": "Invalid action"}), 400

    # fetch or create the single metrics row
    metrics = UserMetrics.query.get(current_user.id)
    if not metrics:
        metrics = UserMetrics(
            user_id=current_user.id,
            username=current_user.name,
            email=current_user.email
        )
        db.session.add(metrics)

    # bump the right counter
    metrics.touch(allowed[action])
    db.session.commit()

    return jsonify({"status": "ok"})

##################################################

# Add this route to your existing app.py
@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        content = data.get('content', '')
        template = data.get('template', 'default')
        
        # Convert markdown to HTML if needed
        html_content = markdown.markdown(content) if content else ''
        
        # Create the complete HTML document with styles
        full_html = create_pdf_html(html_content, template)
        
        # Generate PDF using WeasyPrint
        font_config = FontConfiguration()
        
        # Create temporary file for PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            HTML(string=full_html, base_url=request.url_root).write_pdf(
                tmp_file.name,
                font_config=font_config,
                optimize_images=True
            )
            tmp_file_path = tmp_file.name
        
        # Read PDF content
        with open(tmp_file_path, 'rb') as pdf_file:
            pdf_content = pdf_file.read()
        
        # Clean up temporary file
        os.unlink(tmp_file_path)
        
        # Return PDF as base64 encoded string
        pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        
        return jsonify({
            'success': True,
            'pdf_data': pdf_base64,
            'filename': f'carousel-{template}-{int(time.time())}.pdf'
        })
        
    except Exception as e:
        print(f"PDF generation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def create_pdf_html(content, template):
    """Create complete HTML document with embedded styles for PDF generation"""
    
    # Base styles that work well with WeasyPrint
    base_styles = """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Inter', sans-serif;
            line-height: 1.6;
            color: #333;
            background: white;
        }
        
        .pdf-container {
            width: 210mm;  /* A4 width */
            min-height: 297mm; /* A4 height */
            margin: 0 auto;
            padding: 20mm;
            background: white;
            page-break-inside: avoid;
        }
        
        h1, h2, h3, h4, h5, h6 {
            margin-bottom: 0.5em;
            line-height: 1.2;
            page-break-after: avoid;
        }
        
        p {
            margin-bottom: 1em;
            orphans: 3;
            widows: 3;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 1em;
            page-break-inside: avoid;
        }
        
        th, td {
            padding: 8px 12px;
            border: 1px solid #ddd;
            text-align: left;
        }
        
        th {
            background-color: #f5f5f5;
            font-weight: 600;
        }
        
        code {
            font-family: 'JetBrains Mono', monospace;
            background-color: #f8f9fa;
            padding: 2px 4px;
            border-radius: 3px;
            font-size: 0.9em;
        }
        
        pre {
            background-color: #f8f9fa;
            padding: 1em;
            border-radius: 5px;
            overflow-x: auto;
            margin-bottom: 1em;
            page-break-inside: avoid;
        }
        
        pre code {
            background: none;
            padding: 0;
        }
        
        ul, ol {
            margin-left: 2em;
            margin-bottom: 1em;
        }
        
        li {
            margin-bottom: 0.5em;
        }
        
        blockquote {
            border-left: 4px solid #007bff;
            margin: 1em 0;
            padding-left: 1em;
            font-style: italic;
        }
        
        img {
            max-width: 100%;
            height: auto;
            page-break-inside: avoid;
        }
        
        /* Page break utilities */
        .page-break {
            page-break-before: always;
        }
        
        .no-break {
            page-break-inside: avoid;
        }
    </style>
    """
    
    # Template-specific styles
    template_styles = get_template_styles(template)
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Carousel PDF - {template}</title>
        {base_styles}
        {template_styles}
    </head>
    <body>
        <div class="pdf-container {template}-template">
            {content}
        </div>
    </body>
    </html>
    """

def get_template_styles(template):
    """Return template-specific CSS styles"""
    
    styles_map = {
        'tech-neural': """
        <style>
            .tech-neural-template {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .tech-neural-template h1, .tech-neural-template h2 {
                color: #fff;
                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }
            .tech-neural-template code {
                background: rgba(255,255,255,0.1);
                color: #e1e8ff;
            }
            .tech-neural-template pre {
                background: rgba(0,0,0,0.3);
                border: 1px solid rgba(255,255,255,0.1);
            }
        </style>
        """,
        
        'tech-quantum': """
        <style>
            .tech-quantum-template {
                background: #0a0a0a;
                color: #00ff88;
            }
            .tech-quantum-template h1, .tech-quantum-template h2 {
                color: #00ff88;
                text-shadow: 0 0 10px rgba(0,255,136,0.5);
            }
            .tech-quantum-template code {
                background: rgba(0,255,136,0.1);
                color: #00ff88;
            }
        </style>
        """,
        
        'product-modern': """
        <style>
            .product-modern-template {
                background: linear-gradient(135deg, #ff6b6b 0%, #ffa500 100%);
                color: white;
            }
            .product-modern-template h1, .product-modern-template h2 {
                color: #fff;
            }
        </style>
        """,
        
        'finance-gold': """
        <style>
            .finance-gold-template {
                background: linear-gradient(135deg, #f7931e 0%, #ffd700 100%);
                color: #2c3e50;
            }
            .finance-gold-template h1, .finance-gold-template h2 {
                color: #2c3e50;
                font-weight: 700;
            }
        </style>
        """,
        
        'health-care': """
        <style>
            .health-care-template {
                background: linear-gradient(135deg, #56ab2f 0%, #a8e6cf 100%);
                color: #2c3e50;
            }
        </style>
        """,
        
        'saas-modern': """
        <style>
            .saas-modern-template {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
        </style>
        """,
        
        'dark-neon': """
        <style>
            .dark-neon-template {
                background: #0f0f23;
                color: #00ffff;
            }
            .dark-neon-template h1, .dark-neon-template h2 {
                color: #ff00ff;
                text-shadow: 0 0 10px rgba(255,0,255,0.5);
            }
        </style>
        """
    }
    
    return styles_map.get(template, '<style></style>')

##################################################

if __name__ == '__main__':
    app.run(host="127.0.0.1", debug=True, port=8000)

