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
from flask import Flask, request, jsonify, send_file
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
import tempfile
import os
import base64
from io import BytesIO
import markdown
import time
import requests

# Replace your existing /generate-pdf endpoint with this enhanced version
@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        content = data.get('content', '')
        template = data.get('template', 'tech-neural')
        styles = data.get('styles', '')  # New: capture styles from frontend
        
        # Create the complete HTML document with all styles
        full_html = create_enhanced_pdf_html(content, template, styles)
        
        # Generate PDF using WeasyPrint
        font_config = FontConfiguration()
        
        # Create temporary file for PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            HTML(string=full_html, base_url=request.url_root).write_pdf(
                tmp_file.name,
                font_config=font_config,
                optimize_images=True,
                presentational_hints=True  # This helps preserve more styling
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

def create_enhanced_pdf_html(content, template, captured_styles=''):
    """Create complete HTML document with all captured styles"""
    
    # Complete template styles - all your templates
    complete_template_styles = f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Playfair+Display:wght@400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: 'Inter', sans-serif;
            line-height: 1.6;
            background: white;
            width: 210mm;
            min-height: 297mm;
            margin: 0;
            padding: 0;
        }}
        
        .pdf-container {{
            width: 100%;
            min-height: 100vh;
            padding: 15mm;
            page-break-inside: avoid;
        }}
        
        /* Base Template Styles */
        .template-base {{
            width: 100%;
            min-height: 250mm;
            padding: 2rem;
            border-radius: 12px;
            position: relative;
            overflow: hidden;
        }}
        
        /* TECH NEURAL */
        .tech-neural-template {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            position: relative;
        }}
        
        .tech-neural-template::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: radial-gradient(circle at 20% 50%, rgba(255,255,255,0.1) 0%, transparent 50%),
                        radial-gradient(circle at 80% 20%, rgba(255,255,255,0.05) 0%, transparent 50%);
            pointer-events: none;
        }}
        
        .tech-neural-template h1, .tech-neural-template h2, .tech-neural-template h3 {{
            color: #fff;
            text-shadow: 0 2px 10px rgba(0,0,0,0.3);
            font-weight: 700;
            margin-bottom: 1rem;
        }}
        
        .tech-neural-template h1 {{ font-size: 2.5rem; }}
        .tech-neural-template h2 {{ font-size: 2rem; }}
        .tech-neural-template h3 {{ font-size: 1.5rem; }}
        
        .tech-neural-template p {{
            color: rgba(255,255,255,0.9);
            font-size: 1.1rem;
            margin-bottom: 1rem;
        }}
        
        .tech-neural-template code {{
            background: rgba(255,255,255,0.15);
            color: #e1e8ff;
            padding: 4px 8px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .tech-neural-template pre {{
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
        }}
        
        .tech-neural-template table {{
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .tech-neural-template th {{
            background: rgba(255,255,255,0.2);
            color: white;
            font-weight: 600;
        }}
        
        .tech-neural-template td {{
            color: rgba(255,255,255,0.9);
            border-color: rgba(255,255,255,0.1);
        }}
        
        /* TECH QUANTUM */
        .tech-quantum-template {{
            background: #0a0a0a;
            color: #00ff88;
            position: relative;
        }}
        
        .tech-quantum-template::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: 
                radial-gradient(circle at 25% 25%, rgba(0,255,136,0.1) 0%, transparent 50%),
                radial-gradient(circle at 75% 75%, rgba(0,255,255,0.05) 0%, transparent 50%);
        }}
        
        .tech-quantum-template h1, .tech-quantum-template h2, .tech-quantum-template h3 {{
            color: #00ff88;
            text-shadow: 0 0 20px rgba(0,255,136,0.5);
            font-weight: 700;
        }}
        
        .tech-quantum-template code {{
            background: rgba(0,255,136,0.1);
            color: #00ff88;
            border: 1px solid rgba(0,255,136,0.3);
        }}
        
        .tech-quantum-template pre {{
            background: rgba(0,20,10,0.8);
            border: 1px solid rgba(0,255,136,0.3);
        }}
        
        /* PRODUCT MODERN */
        .product-modern-template {{
            background: linear-gradient(135deg, #ff6b6b 0%, #ffa500 100%);
            color: white;
        }}
        
        .product-modern-template h1, .product-modern-template h2, .product-modern-template h3 {{
            color: #fff;
            font-weight: 800;
            text-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }}
        
        /* PRODUCT PREMIUM */
        .product-premium-template {{
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: #ecf0f1;
        }}
        
        .product-premium-template h1, .product-premium-template h2, .product-premium-template h3 {{
            color: #f39c12;
            font-weight: 700;
        }}
        
        /* FINANCE GOLD */
        .finance-gold-template {{
            background: linear-gradient(135deg, #f7931e 0%, #ffd700 100%);
            color: #2c3e50;
        }}
        
        .finance-gold-template h1, .finance-gold-template h2, .finance-gold-template h3 {{
            color: #2c3e50;
            font-weight: 800;
        }}
        
        /* FINANCE ELITE */
        .finance-elite-template {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #f8f9fa;
        }}
        
        .finance-elite-template h1, .finance-elite-template h2, .finance-elite-template h3 {{
            color: #ffd700;
            font-weight: 700;
        }}
        
        /* HEALTH CARE */
        .health-care-template {{
            background: linear-gradient(135deg, #56ab2f 0%, #a8e6cf 100%);
            color: #2c3e50;
        }}
        
        .health-care-template h1, .health-care-template h2, .health-care-template h3 {{
            color: #27ae60;
            font-weight: 700;
        }}
        
        /* HEALTH MEDICAL */
        .health-medical-template {{
            background: linear-gradient(135deg, #0f4c75 0%, #3282b8 100%);
            color: white;
        }}
        
        .health-medical-template h1, .health-medical-template h2, .health-medical-template h3 {{
            color: #bbdeff;
            font-weight: 700;
        }}
        
        /* SAAS MODERN */
        .saas-modern-template {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        
        .saas-modern-template h1, .saas-modern-template h2, .saas-modern-template h3 {{
            color: #fff;
            font-weight: 700;
        }}
        
        /* SAAS ENTERPRISE */
        .saas-enterprise-template {{
            background: linear-gradient(135deg, #2c3e50 0%, #4a69bd 100%);
            color: #ecf0f1;
        }}
        
        .saas-enterprise-template h1, .saas-enterprise-template h2, .saas-enterprise-template h3 {{
            color: #74b9ff;
            font-weight: 700;
        }}
        
        /* DARK NEON */
        .dark-neon-template {{
            background: #0f0f23;
            color: #00ffff;
            position: relative;
        }}
        
        .dark-neon-template::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: 
                radial-gradient(circle at 30% 40%, rgba(255,0,255,0.1) 0%, transparent 60%),
                radial-gradient(circle at 70% 70%, rgba(0,255,255,0.1) 0%, transparent 60%);
        }}
        
        .dark-neon-template h1, .dark-neon-template h2, .dark-neon-template h3 {{
            color: #ff00ff;
            text-shadow: 0 0 20px rgba(255,0,255,0.8);
            font-weight: 700;
        }}
        
        .dark-neon-template code {{
            background: rgba(255,0,255,0.1);
            color: #ff00ff;
            border: 1px solid rgba(255,0,255,0.3);
        }}
        
        /* SKETCHY MINIMAL */
        .sketchy-minimal-template {{
            background: #fefefe;
            color: #2c3e50;
            font-family: 'Space Grotesk', sans-serif;
        }}
        
        .sketchy-minimal-template h1, .sketchy-minimal-template h2, .sketchy-minimal-template h3 {{
            color: #2c3e50;
            font-weight: 600;
        }}
        
        /* EXECUTIVE BOARD */
        .executive-board-template {{
            background: #f8f9fa;
            color: #2c3e50;
            font-family: 'Playfair Display', serif;
        }}
        
        .executive-board-template h1, .executive-board-template h2, .executive-board-template h3 {{
            color: #1a252f;
            font-weight: 700;
        }}
        
        /* GRADIENT PRO */
        .gradient-pro-template {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            color: white;
        }}
        
        .gradient-pro-template h1, .gradient-pro-template h2, .gradient-pro-template h3 {{
            color: #fff;
            font-weight: 800;
        }}
        
        /* RETRO */
        .retro-template {{
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 50%, #ffcc02 100%);
            color: #2c3e50;
        }}
        
        .retro-template h1, .retro-template h2, .retro-template h3 {{
            color: #2c3e50;
            font-weight: 800;
        }}
        
        /* GLASS MORPH */
        .glass-morph-template {{
            background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            color: #2c3e50;
        }}
        
        .glass-morph-template h1, .glass-morph-template h2, .glass-morph-template h3 {{
            color: #2c3e50;
            font-weight: 700;
        }}
        
        /* Common styles for all templates */
        h1, h2, h3, h4, h5, h6 {{
            margin-bottom: 0.5em;
            line-height: 1.2;
            page-break-after: avoid;
        }}
        
        p {{
            margin-bottom: 1em;
            orphans: 3;
            widows: 3;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 1em;
            page-break-inside: avoid;
        }}
        
        th, td {{
            padding: 8px 12px;
            border: 1px solid rgba(255,255,255,0.2);
            text-align: left;
        }}
        
        th {{
            font-weight: 600;
        }}
        
        code {{
            font-family: 'JetBrains Mono', monospace;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        
        pre {{
            border-radius: 8px;
            overflow-x: auto;
            margin-bottom: 1em;
            page-break-inside: avoid;
            padding: 1rem;
        }}
        
        pre code {{
            background: none;
            padding: 0;
            border: none;
        }}
        
        ul, ol {{
            margin-left: 2em;
            margin-bottom: 1em;
        }}
        
        li {{
            margin-bottom: 0.5em;
        }}
        
        blockquote {{
            border-left: 4px solid currentColor;
            margin: 1em 0;
            padding-left: 1em;
            font-style: italic;
            opacity: 0.8;
        }}
        
        img {{
            max-width: 100%;
            height: auto;
            page-break-inside: avoid;
        }}
        
        /* Additional captured styles */
        {captured_styles}
    </style>
    """
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Carousel PDF - {template}</title>
        {complete_template_styles}
    </head>
    <body>
        <div class="pdf-container">
            <div class="{template}-template template-base">
                {content}
            </div>
        </div>
    </body>
    </html>
    """

##################################################

if __name__ == '__main__':
    app.run(host="127.0.0.1", debug=True, port=8000)

