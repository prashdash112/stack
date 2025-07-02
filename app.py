from flask import Flask, render_template, request, jsonify, redirect, url_for,send_file,Response
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
from bs4 import BeautifulSoup

import tempfile
import base64
from io import BytesIO
import markdown 
import time
import json 




app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
# openai.api_key = os.getenv("OPENAI_API_KEY")  # Set in environment
app.secret_key = os.environ['SECRET_KEY']
# Add this near the top with other configurations
app.config['SESSION_COOKIE_DOMAIN'] = '.geniuspostai.com'  # Allow cookies across subdomains
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
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

########################User Feedback ################################
class UserFeedback(db.Model):
    __tablename__ = "user_feedback"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(50), db.ForeignKey("user.id"), nullable=False)
    username = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    star_rating = db.Column(db.Integer, nullable=False)  # 1-5
    improvement_suggestion = db.Column(db.Text, nullable=True)  # What could make it 100x better
    would_recommend = db.Column(db.Boolean, nullable=False)  # True=Yes, False=No
    submitted_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    
    user = db.relationship("User", backref="feedback")
    
    def __repr__(self):
        return f"<UserFeedback user_id={self.user_id} rating={self.star_rating}>"
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

################################################################################
# 1. ADD THIS NEW STREAMING ENDPOINT - Replace your existing /generate route

@app.route('/generate-stream', methods=['POST'])
def generate_stream():
    """Streaming endpoint that sends chunks as they're generated"""
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    prompt_decorator = 'Important: 1) Dont give unnecessary information. 2) Sound as human-like as possible. Understand when to be creative, formal, casual, or smart. 3) Always use headings and subheadings unless mentioned otherwise. 4) Always split the code into smaller chunks.' 
    prompt = prompt + prompt_decorator
    
    if not prompt:
        return jsonify({'error': 'Prompt is required.'}), 400

    def generate_chunks():
        """Generator function that yields chunks as they come from Claude"""
        try:
            client = anthropic.Anthropic(api_key=os.environ["CLAUDE_APIKEY"])
            
            # 🔥 USE STREAMING API - This is the key change
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=1200,
                temperature=1,
                messages=[{
                    "role": "user", 
                    "content": prompt
                }]
            ) as stream:
                for text in stream.text_stream:
                    if text:  # Only send non-empty chunks
                        # Format as Server-Sent Events
                        yield f"data: {json.dumps({'chunk': text, 'done': False})}\n\n"
            
            # Send completion signal
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
            
        except Exception as e:
            # Send error
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return Response(
        generate_chunks(),
        content_type='text/plain; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
    )

# 2. KEEP YOUR EXISTING /generate ROUTE AS FALLBACK (in case streaming fails)
###################################################################################
@app.route('/generate', methods=['POST'])
def generate():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    prompt_decorator = 'Important: 1) Dont give unnecessary information. 2) Sound as human-like as possible. Understand when to be creative, formal, casual, or smart. 3) Always use headings and subheadings unless mentioned otherwise. 4) Always split the code into smaller chunks.' 
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
            max_tokens=1200,
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

#####################submit_feedback route#############################
@app.route("/submit_feedback", methods=["POST"])
@login_required
def submit_feedback():
    try:
        data = request.get_json() or {}
        
        # Validate required fields
        star_rating = data.get("star_rating")
        would_recommend = data.get("would_recommend")
        improvement_suggestion = data.get("improvement_suggestion", "").strip()
        
        if not star_rating or star_rating not in [1, 2, 3, 4, 5]:
            return jsonify({"error": "Valid star rating (1-5) is required"}), 400
            
        if would_recommend not in [True, False]:
            return jsonify({"error": "Recommendation answer is required"}), 400
        
        # Create feedback record
        feedback = UserFeedback(
            user_id=current_user.id,
            username=current_user.name,
            email=current_user.email,
            star_rating=star_rating,
            improvement_suggestion=improvement_suggestion if improvement_suggestion else None,
            would_recommend=would_recommend
        )
        
        db.session.add(feedback)
        db.session.commit()
        
        return jsonify({"status": "success", "message": "Thank you for your feedback!"})
        
    except Exception as e:
        print(f"Feedback submission error: {str(e)}")
        return jsonify({"error": "Failed to submit feedback"}), 500

@app.route("/check_feedback_status", methods=["GET"])

@login_required
def check_feedback_status():
    """Check if user has already submitted feedback"""
    existing_feedback = UserFeedback.query.filter_by(user_id=current_user.id).first()
    return jsonify({"has_submitted": existing_feedback is not None})


# Replace your existing create_enhanced_pdf_html function with this enhanced version

# def create_enhanced_pdf_html(content, template, captured_styles=''): 
#     """Create complete HTML document with smart page break handling"""
    
#     complete_template_styles = f"""
#     <style>
#         @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Playfair+Display:wght@400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
        
#         /* PDF PAGE CONTROL - CUSTOM SIZE */
#         @page {{
#             size: 1080px 1350px;
#             margin: 8px;
#             padding: 0px;
#         }}
        
#         /* ✅ FIRST PAGE ONLY - Footer */
#         @page :first {{
#             margin: 8px 8px 30px 8px; 
            
#             @bottom-center {{
#                 content: "Generated with GeniusPost AI";
#                 font-family: 'Space Grotesk', sans-serif;
#                 font-size: 18px;
#                 font-weight: 700;
#                 color: #2c3e50;
#                 background: rgba(255,255,255,0.9);
#                 padding: 8px 16px;
#                 border-radius: 20px;
#                 letter-spacing: 1px;
#                 text-transform: uppercase;
#                 box-shadow: 0 2px 8px rgba(0,0,0,0.15);
#                 margin-top: 5px;
#             }}
#         }}
        
#         * {{
#             box-sizing: border-box;
#             margin: 0;
#             padding: 0;
#         }}
        
#         html, body {{
#             width: 1064px;
#             margin: 0 !important;
#             padding: 0px !important;
#             font-family: 'Inter', sans-serif;
#         }}
        
#         .pdf-container {{
#             width: 1064px;
#             margin: 0;
#             padding: 0;
#             position: relative;
#         }}
        
#         .template-base {{
#             width: 1064px !important;
#             min-height: 1324px !important;
#             margin: 0 !important;
#             padding: 30px !important;
#             position: relative;
#             box-sizing: border-box;
#             page-break-inside: auto;
#         }}
        
#         /* 🔥 SMART PAGE BREAK CONTROLS - BULLETPROOF SOLUTION */
        
#         /* Allow content to break naturally */
#         h1, h2, h3, h4, h5, h6 {{
#             page-break-after: auto !important;
#             page-break-inside: avoid;
#             page-break-before: auto;
#             margin-top: 20px;
#             margin-bottom: 15px;
#             orphans: 2;
#             widows: 2;
#         }}

#         /* Prevent orphans/widows but allow breaks */
#         p {{
#             page-break-inside: auto;
#             orphans: 2;
#             widows: 2;
#             margin-bottom: 12px;
#             line-height: 1.6;
#         }}
        
#         /* Smart list handling */
#         ul, ol {{
#             page-break-inside: auto;
#             margin: 15px 0;
#         }}
        
#         li {{
#             page-break-inside: auto;
#             orphans: 2;
#             widows: 2;
#             margin-bottom: 8px;
#         }}
        
#         /* Long content elements - allow smart breaking */
#         blockquote {{
#             page-break-inside: auto;
#             margin: 20px 0;
#             padding: 15px 20px;
#             border-left: 4px solid #ddd;
#             background: #f9f9f9;
#             orphans: 2;
#             widows: 2;
#         }}
        
#         /* Code blocks - allow breaking with proper formatting */
#         pre {{
#             page-break-inside: auto;
#             margin: 15px 0;
#             padding: 20px;
#             background: #f5f5f5;
#             border-radius: 8px;
#             overflow-wrap: break-word;
#             white-space: pre-wrap;
#             font-size: 14px;
#             line-height: 1.4;
#             orphans: 3;
#             widows: 3;
#         }}
        
#         code {{
#             page-break-inside: auto;
#             word-wrap: break-word;
#             overflow-wrap: break-word;
#         }}
        
#         /* Tables - smart breaking */
#         table {{
#             page-break-inside: auto;
#             margin: 20px 0;
#             width: 100%;
#             border-collapse: collapse;
#         }}
        
#         thead {{
#             page-break-after: avoid;
#         }}
        
#         tbody tr {{
#             page-break-inside: avoid;
#             page-break-after: auto;
#         }}
        
#         th, td {{
#             padding: 12px;
#             border: 1px solid #ddd;
#             vertical-align: top;
#         }}
        
#         /* Images - keep together but allow page breaks around them */
#         img {{
#             max-width: 1004px !important;
#             width: 100% !important;
#             height: auto !important;
#             display: block !important;
#             page-break-inside: avoid;
#             page-break-before: auto;
#             page-break-after: auto;
#             margin: 20px auto !important;
#             object-fit: contain !important;
#             border-radius: 16px !important;
#             position: relative !important;
#         }}
        
#         /* Div containers - allow natural breaking */
#         div {{
#             page-break-inside: auto;
#         }}
        
#         /* Special handling for long paragraphs */
#         p.long-content {{
#             page-break-inside: auto;
#             orphans: 3;
#             widows: 3;
#         }}
        
#         /* 🔥 SMART SPACING THAT PREVENTS BLANK PAGES */
        
#         /* Reduce excessive margins that cause page breaks */
#         h1:first-child, h2:first-child, h3:first-child {{
#             margin-top: 0 !important;
#             padding-top: 10px;
#         }}
        
#         /* Ensure reasonable spacing */
#         .template-base > *:first-child {{
#             margin-top: 0 !important;
#         }}
        
#         .template-base > *:last-child {{
#             margin-bottom: 0 !important;
#         }}
        
#         /* Prevent large gaps */
#         br + br {{
#             display: none;
#         }}
        
#         /* 🔥 ADVANCED ORPHAN/WIDOW CONTROL */
        
#         /* Apply to all text content */
#         p, li, td, th, blockquote, figcaption {{
#             orphans: 2;
#             widows: 2;
#         }}
        
#         /* Stricter control for headings */
#         h1, h2, h3 {{
#             orphans: 3;
#             widows: 3;
#         }}
        
#         /* 🔥 FORCE CONTENT TO FLOW NATURALLY */
        
#         /* Remove restrictive page-break-inside: avoid from containers */
#         .content-section, .card, .panel {{
#             page-break-inside: auto !important;
#         }}
        
#         /* Allow flexible breaking for content blocks */
#         .content-block {{
#             page-break-inside: auto;
#             margin: 10px 0;
#         }}
        
#         /* Additional captured styles */
#         {captured_styles}
        
#         /* 🔥 OVERRIDE ANY RESTRICTIVE STYLES FROM CAPTURED CSS */
        
#         /* Force natural page breaking for common containers */
#         section, article, aside, main {{
#             page-break-inside: auto !important;
#         }}
        
#         /* Ensure text can break naturally */
#         span, strong, em, b, i {{
#             page-break-inside: auto;
#         }}
        
#         /* Smart handling of flex/grid layouts in print */
#         .flex, .grid, .container {{
#             display: block !important;
#             page-break-inside: auto !important;
#         }}
#     </style>
#     """
    
#     # 🔥 PREPROCESS CONTENT FOR BETTER PAGE BREAKS
#     processed_content = preprocess_content_for_pdf(content)
    
#     return f"""
#     <!DOCTYPE html>
#     <html>
#     <head>
#         <meta charset="UTF-8">
#         <title>Carousel PDF - {template}</title>
#         {complete_template_styles}
#     </head>
#     <body>
#         <div class="pdf-container">
#             <div class="{template}-template template-base">
#                 {processed_content}
#             </div>
#         </div>
#     </body>
#     </html>
#     """

def create_enhanced_pdf_html(content, template, captured_styles=''):
    """Create complete HTML document with variable fonts for PDF generation"""
    
    # Get absolute path to static directory
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
    fonts_dir = os.path.join(static_dir, 'fonts')
    
    # Debug: Print font paths to verify they exist
    print(f"Static directory: {static_dir}")
    print(f"Fonts directory: {fonts_dir}")
    print(f"Fonts directory exists: {os.path.exists(fonts_dir)}")
    
    # Generate variable font-face declarations with absolute file paths
    variable_font_css = f"""
        /* Variable Font Definitions for PDF */
        @font-face {{
            font-family: 'Inter';
            src: url('file://{fonts_dir}/Inter-VariableFont.ttf') format('truetype');
            font-weight: 100 900;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Inter';
            src: url('file://{fonts_dir}/Inter-Italic-VariableFont.ttf') format('truetype');
            font-weight: 100 900;
            font-style: italic;
        }}

        @font-face {{
            font-family: 'JetBrains Mono';
            src: url('file://{fonts_dir}/JetBrainsMono-VariableFont.ttf') format('truetype');
            font-weight: 100 800;
            font-style: normal;
        }}
        @font-face {{ 
            font-family: 'JetBrains Mono';
            src: url('file://{fonts_dir}/JetBrainsMono-Italic-VariableFont.ttf') format('truetype');
            font-weight: 100 800;
            font-style: italic;
        }}

        @font-face {{
            font-family: 'Playfair Display';
            src: url('file://{fonts_dir}/PlayfairDisplay-VariableFont.ttf') format('truetype');
            font-weight: 400 900;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Playfair Display';
            src: url('file://{fonts_dir}/PlayfairDisplay-Italic-VariableFont.ttf') format('truetype');
            font-weight: 400 900;
            font-style: italic;
        }}

        @font-face {{
            font-family: 'Space Grotesk';
            src: url('file://{fonts_dir}/SpaceGrotesk-VariableFont.ttf') format('truetype');
            font-weight: 300 700;
            font-style: normal;
        }}

        @font-face {{
            font-family: 'Crimson Pro';
            src: url('file://{fonts_dir}/CrimsonPro-VariableFont.ttf') format('truetype');
            font-weight: 200 900;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Crimson Pro';
            src: url('file://{fonts_dir}/CrimsonPro-Italic-VariableFont.ttf') format('truetype');
            font-weight: 200 900;
            font-style: italic;
        }}

        @font-face {{
            font-family: 'Fraunces';
            src: url('file://{fonts_dir}/Fraunces-VariableFont.ttf') format('truetype');
            font-weight: 100 900;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Fraunces';
            src: url('file://{fonts_dir}/Fraunces-Italic-VariableFont.ttf') format('truetype');
            font-weight: 100 900;
            font-style: italic;
        }}

        @font-face {{
            font-family: 'Open Sans';
            src: url('file://{fonts_dir}/OpenSans-VariableFont.ttf') format('truetype');
            font-weight: 300 800;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Open Sans';
            src: url('file://{fonts_dir}/OpenSans-Italic-VariableFont.ttf') format('truetype');
            font-weight: 300 800;
            font-style: italic;
        }}

        /* Static fonts */
        @font-face {{
            font-family: 'Kalam';
            src: url('file://{fonts_dir}/Kalam-Light.ttf') format('truetype');
            font-weight: 300;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Kalam';
            src: url('file://{fonts_dir}/Kalam-Regular.ttf') format('truetype');
            font-weight: 400;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'Kalam';
            src: url('file://{fonts_dir}/Kalam-Bold.ttf') format('truetype');
            font-weight: 700;
            font-style: normal;
        }}
    """
    
    complete_template_styles = f"""
    <style>
        /* VARIABLE FONT DEFINITIONS FOR PDF */
        {variable_font_css}
        
        /* PDF PAGE CONTROL - CUSTOM SIZE */
        @page {{
            size: 1080px 1350px;
            margin: 8px;
            padding: 0px;
        }}
        
        /* ✅ FIRST PAGE ONLY - Footer */
        @page :first {{
            margin: 8px 8px 30px 8px; 
            
            @bottom-center {{
                content: "Generated with GeniusPost AI";
                font-family: 'Space Grotesk', Arial, sans-serif;
                font-size: 18px;
                font-weight: 700;
                color: #2c3e50;
                background: rgba(255,255,255,0.9);
                padding: 8px 16px;
                border-radius: 20px;
                letter-spacing: 1px;
                text-transform: uppercase;
                box-shadow: 0 2px 8px rgba(0,0,0,0.15);
                margin-top: 5px;
            }}
        }}
        
        /* BASIC PDF LAYOUT - NO FONT OVERRIDES */
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        html, body {{
            width: 1064px;
            margin: 0 !important;
            padding: 0px !important;
            /* NO font-family here - let captured styles handle it */
        }}
        
        .pdf-container {{
            width: 1064px;
            margin: 0;
            padding: 0;
            position: relative;
        }}
        
        .template-base {{
            width: 1064px !important;
            min-height: 1324px !important;
            margin: 0 !important;
            padding: 30px !important;
            position: relative;
            box-sizing: border-box;
            page-break-inside: auto;
        }}
        
        /* 🔥 PAGE BREAK CONTROLS - NO FONT OVERRIDES */
        h1, h2, h3, h4, h5, h6 {{
            page-break-after: auto !important;
            page-break-inside: avoid;
            page-break-before: auto;
            margin-top: 20px;
            margin-bottom: 15px;
            orphans: 2;
            widows: 2;
        }}

        p {{
            page-break-inside: auto;
            orphans: 2;
            widows: 2;
            margin-bottom: 12px;
            line-height: 1.6;
            /* NO font-family - let captured styles handle it */
        }}
        
        ul, ol {{
            page-break-inside: auto;
            margin: 15px 0;
        }}
        
        li {{
            page-break-inside: auto;
            orphans: 2;
            widows: 2;
            margin-bottom: 8px;
            /* NO font-family - let captured styles handle it */
        }}
        
        blockquote {{
            page-break-inside: auto;
            margin: 20px 0;
            padding: 15px 20px;
            border-left: 4px solid #ddd;
            background: #f9f9f9;
            orphans: 2;
            widows: 2;
        }}
        
        table {{
            page-break-inside: auto;
            margin: 20px 0;
            width: 100%;
            border-collapse: collapse;
        }}
        
        thead {{
            page-break-after: avoid;
        }}
        
        tbody tr {{
            page-break-inside: avoid;
            page-break-after: auto;
        }}
        
        th, td {{
            padding: 12px;
            border: 1px solid #ddd;
            vertical-align: top;
            /* NO font-family - let captured styles handle it */
        }}
        
        th {{
            font-weight: 600;
            /* NO font-family - let captured styles handle it */
        }}
        
        img {{
            max-width: 1004px !important;
            width: 100% !important;
            height: auto !important;
            display: block !important;
            page-break-inside: avoid;
            page-break-before: auto;
            page-break-after: auto;
            margin: 20px auto !important;
            object-fit: contain !important;
            border-radius: 16px !important;
            position: relative !important;
        }}
        
        div {{
            page-break-inside: auto;
        }}
        
        /* CAPTURED STYLES - This handles all fonts and styling */
        {captured_styles}
        
        /* 🔥 MINIMAL OVERRIDES - Only fix what breaks in PDF */
        @import {{ display: none !important; }}
        
        /* Only override code fonts (functional requirement) */
        pre, code {{
            font-family: 'JetBrains Mono', 'Courier New', monospace !important;
        }}
        
        /* Print optimization */
        * {{
            -webkit-print-color-adjust: exact !important;
            color-adjust: exact !important;
        }}
    </style>
    """
    
    # Preprocess content for better page breaks
    processed_content = preprocess_content_for_pdf(content)
    
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
                {processed_content}
            </div>
        </div>
    </body>
    </html>
    """


def preprocess_content_for_pdf(content):
    """
    Preprocess HTML content to optimize for PDF page breaks
    """
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
        # 🔥 SMART CONTENT SPLITTING
        
        # Find very long paragraphs and add soft breaks
        for p in soup.find_all('p'):
            if p.get_text() and len(p.get_text()) > 800:  # Long paragraphs
                p['class'] = p.get('class', []) + ['long-content']
                
                # Split very long paragraphs at sentence boundaries
                text = p.get_text()
                if len(text) > 1200:  # Very long content
                    sentences = text.split('. ')
                    if len(sentences) > 3:
                        # Split into smaller paragraphs
                        p.clear()
                        mid_point = len(sentences) // 2
                        
                        # First half
                        first_half = '. '.join(sentences[:mid_point]) + '.'
                        first_p = soup.new_tag('p', **{'class': 'long-content'})
                        first_p.string = first_half
                        
                        # Second half  
                        second_half = '. '.join(sentences[mid_point:])
                        if not second_half.endswith('.'):
                            second_half += '.'
                        second_p = soup.new_tag('p', **{'class': 'long-content'})
                        second_p.string = second_half
                        
                        # Replace original paragraph
                        p.insert_before(first_p)
                        p.insert_before(second_p)
                        p.decompose()
        
        # 🔥 OPTIMIZE LISTS FOR PAGE BREAKS
        for ul in soup.find_all(['ul', 'ol']):
            items = ul.find_all('li')
            if len(items) > 8:  # Long lists
                # Add page break hints every 6-8 items
                for i, item in enumerate(items):
                    if i > 0 and i % 7 == 0:  # Every 7th item
                        item['style'] = item.get('style', '') + ' page-break-before: auto;'
        
        # 🔥 HANDLE LARGE CODE BLOCKS
        for pre in soup.find_all('pre'):
            code_text = pre.get_text()
            if len(code_text) > 1000:  # Long code blocks
                # Add line break opportunities
                lines = code_text.split('\n')
                if len(lines) > 25:  # Many lines
                    # Split into smaller code blocks
                    pre.clear()
                    chunk_size = 20
                    
                    for i in range(0, len(lines), chunk_size):
                        chunk_lines = lines[i:i + chunk_size]
                        new_pre = soup.new_tag('pre')
                        new_pre.string = '\n'.join(chunk_lines)
                        
                        if i > 0:  # Add spacing between chunks
                            spacing = soup.new_tag('div', style='height: 10px;')
                            pre.insert_before(spacing)
                        
                        pre.insert_before(new_pre)
                    
                    pre.decompose()
        
        # 🔥 ADD SMART BREAK OPPORTUNITIES
        
        # Add break opportunities after every few headings
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        for i, heading in enumerate(headings):
            if i > 0 and i % 3 == 0:  # Every 3rd heading
                # Add a subtle break opportunity
                break_div = soup.new_tag('div', **{
                    'class': 'page-break-opportunity',
                    'style': 'page-break-before: auto; height: 1px;'
                })
                heading.insert_before(break_div)
        
        # 🔥 REMOVE EXCESSIVE WHITE SPACE
        
        # Remove multiple consecutive <br> tags
        for br in soup.find_all('br'):
            next_sibling = br.next_sibling
            if next_sibling and next_sibling.name == 'br':
                br.decompose()
        
        # Clean up empty paragraphs
        for p in soup.find_all('p'):
            if not p.get_text().strip() and not p.find('img'):
                p.decompose()
        
        return str(soup)
    
    except Exception as e:
        print(f"Content preprocessing error: {e}")
        return content  # Return original content if preprocessing fails


# 🔥 ENHANCED PDF GENERATION WITH BETTER WEASYPRINT SETTINGS
@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        content = data.get('content', '')
        template = data.get('template', 'tech-neural')
        styles = data.get('styles', '')
        
        # Create the complete HTML document with smart page breaks
        full_html = create_enhanced_pdf_html(content, template, styles)
        
        # 🔥 ENHANCED WEASYPRINT CONFIGURATION
        font_config = FontConfiguration()
        
        # Create temporary file for PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            HTML(
                string=full_html, 
                base_url=request.url_root,
                encoding='utf-8'
            ).write_pdf(
                tmp_file.name,
                font_config=font_config,
                optimize_images=False,
                presentational_hints=True,
                # 🔥 ENHANCED SETTINGS FOR BETTER PAGE BREAKING
                stylesheets=[],
                attachments=[],
                # Additional WeasyPrint options for better rendering
                uncompressed_pdf=False,  # Keep file size reasonable
                pdf_version='1.7',       # Modern PDF version
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

@app.route("/debug")
def debug():
    return jsonify({
        "host": request.host,
        "redirect_uri": os.environ.get("REDIRECT_URI"),
        "current_user": current_user.is_authenticated if current_user else False
    })

@app.route('/debug-fonts')
def debug_fonts():
    """Debug route to check variable font availability"""
    fonts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'fonts'))
    
    required_fonts = [
        # Variable fonts
        'Inter-VariableFont.ttf',
        'Inter-Italic-VariableFont.ttf',
        'JetBrainsMono-VariableFont.ttf',
        'JetBrainsMono-Italic-VariableFont.ttf',
        'PlayfairDisplay-VariableFont.ttf',
        'PlayfairDisplay-Italic-VariableFont.ttf',
        'SpaceGrotesk-VariableFont.ttf',
        'SpaceGrotesk-Italic-VariableFont.ttf',
        'CrimsonPro-VariableFont.ttf',
        'CrimsonPro-Italic-VariableFont.ttf',
        'Fraunces-VariableFont.ttf',
        'Fraunces-Italic-VariableFont.ttf',
        'OpenSans-VariableFont.ttf',
        'OpenSans-Italic-VariableFont.ttf',
        # Static fonts
        'kalam-light.ttf',
        'kalam-regular.ttf',
        'kalam-bold.ttf'
    ]
    
    font_status = {}
    total_fonts = len(required_fonts)
    fonts_found = 0
    
    for font in required_fonts:
        font_path = os.path.join(fonts_dir, font)
        exists = os.path.exists(font_path)
        if exists:
            fonts_found += 1
        
        font_status[font] = {
            'exists': exists,
            'path': font_path,
            'size': os.path.getsize(font_path) if exists else 0
        }
    
    return jsonify({
        'fonts_dir': fonts_dir,
        'fonts_dir_exists': os.path.exists(fonts_dir),
        'fonts_found': f"{fonts_found}/{total_fonts}",
        'all_fonts_available': fonts_found == total_fonts,
        'fonts': font_status
    })
##################################################

if __name__ == '__main__':
    app.run(host="127.0.0.1", debug=True, port=8000)

