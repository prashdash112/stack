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
# def generate_pdf():
#     try:
#         data = request.get_json()
#         content = data.get('content', '')
#         template = data.get('template', 'tech-neural')
#         styles = data.get('styles', '')  # New: capture styles from frontend
        
#         # Create the complete HTML document with all styles
#         full_html = create_enhanced_pdf_html(content, template, styles)
        
#         # Generate PDF using WeasyPrint
#         font_config = FontConfiguration()
        
#         # Create temporary file for PDF
#         with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
#             HTML(string=full_html, base_url=request.url_root).write_pdf(
#                 tmp_file.name,
#                 font_config=font_config,
#                 optimize_images=True,
#                 presentational_hints=True  # This helps preserve more styling
#             )
#             tmp_file_path = tmp_file.name
        
#         # Read PDF content
#         with open(tmp_file_path, 'rb') as pdf_file:
#             pdf_content = pdf_file.read()
        
#         # Clean up temporary file
#         os.unlink(tmp_file_path)
        
#         # Return PDF as base64 encoded string
#         pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        
#         return jsonify({
#             'success': True,
#             'pdf_data': pdf_base64,
#             'filename': f'carousel-{template}-{int(time.time())}.pdf'
#         })
        
#     except Exception as e:
#         print(f"PDF generation error: {str(e)}")
#         return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        content = data.get('content', '')
        template = data.get('template', 'tech-neural')
        styles = data.get('styles', '')
        
        # Create the complete HTML document with all styles
        full_html = create_enhanced_pdf_html(content, template, styles)
        
        # Generate PDF using WeasyPrint with proper image handling
        font_config = FontConfiguration()
        
        # Create temporary file for PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            HTML(
                string=full_html, 
                base_url=request.url_root,  # ✅ CRITICAL: This allows relative image URLs
                encoding='utf-8'
            ).write_pdf(
                tmp_file.name,
                font_config=font_config,
                optimize_images=False,  # ✅ CHANGED: Don't optimize to prevent corruption
                presentational_hints=True,
                # ✅ NEW: Add these for better image handling
                stylesheets=[],
                attachments=[]
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
    
    complete_template_styles = f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Playfair+Display:wght@400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
        
        /* PDF PAGE CONTROL - CUSTOM SIZE */
        @page {{
            size: 1080px 1350px;
            margin: 0;
            padding: 0;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        html, body {{
            width: 1080px;
            margin: 0 !important;
            padding: 0 !important;
            font-family: 'Inter', sans-serif;
        }}
        
        .pdf-container {{
            width: 1080px;
            margin: 0;
            padding: 0;
            position: relative;
        }}
        
        .template-base {{
            width: 1080px !important;
            min-height: 1350px !important;
            margin: 0 !important;
            padding: 40px !important;
            position: relative;
            box-sizing: border-box;
            page-break-inside: auto;
        }}
        
        /* PAGE BREAK CONTROLS */
        h1, h2, h3, h4, h5, h6 {{
            page-break-after: avoid;
            page-break-inside: avoid;
        }}

        /* IMAGE HANDLING FOR PDF - CRITICAL */
        img {{
            max-width: 100% !important;
            height: auto !important;
            width: 1080px
            display: block !important;
            page-break-inside: avoid;
            margin: 0px 0 !important;
            object-fit: contain !important;
        }}
        
        p, li {{
            orphans: 3;
            widows: 3;
        }}
        
        table, pre, blockquote {{
            page-break-inside: avoid;
        }}
        
        /* Additional captured styles */
        {captured_styles}
    </style>
    """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
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

