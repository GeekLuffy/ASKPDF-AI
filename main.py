import markdown
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import fitz  # PyMuPDF for text-based PDFs
import pytesseract  # OCR for images
import requests  # To call the AI API
from PIL import Image
import sqlite3
from deep_translator import GoogleTranslator
from translate import Translator

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.config["UPLOAD_FOLDER"] = "uploads"

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# --- Database Setup ---
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


# --- Authentication Routes ---
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
        else:
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (email, password) VALUES (?, ?)",
                               (email, generate_password_hash(password)))
                conn.commit()
                session["user"] = email  # Log in the user automatically
                return redirect(url_for("upload_file"))
            except sqlite3.IntegrityError:
                flash("Email already registered. Try logging in.", "danger")
            finally:
                conn.close()

    return render_template("signup.html")


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[0], password):
            session["user"] = email
            return redirect(url_for("upload_file"))
        else:
            flash("Invalid credentials, try again.", "danger")

    return render_template("signin.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("signin"))


# --- PDF Text Extraction ---
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    extracted_text = ""

    for page in doc:
        text = page.get_text("text")
        if text.strip():
            extracted_text += text + "\n"
        else:
            # If no text, apply OCR (for scanned PDFs)
            pix = page.get_pixmap()  # Convert page to an image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            extracted_text += pytesseract.image_to_string(img) + "\n"

    return extracted_text.strip() if extracted_text.strip() else "No text found."



# --- OCR for Scanned PDFs ---
def extract_text_from_image(image_path):
    text = pytesseract.image_to_string(Image.open(image_path))
    return text if text.strip() else "No text detected."


# --- Text Summarization ---
def summarize_text(text):
    api_url = "https://api.qewertyy.dev/models"
    payload = {
        "model_id": 5,  # GPT-3.5 Turbo
        "messages": [
            {
                "role": "user",
                "content": f"Summarize this text:\n{text}"
            }
        ]
    }
    headers = {"Content-Type": "application/json"}

    response = requests.post(api_url, json=payload, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data.get("content", "No summary generated.")
    else:
        return f"Error: {response.text}"


# --- Question Generation ---
def generate_questions(text):
    api_url = "https://api.qewertyy.dev/models"
    payload = {
        "model_id": 5,  # GPT-3.5 Turbo
        "messages": [
            {
                "role": "user",
                "content": f"Generate 10 questions from this text with answers and the answers should be in next line after question and mention answer proper as answer: and for making text bold use html formatting and don't mention html formatting in response:\n{text}"

            }
        ]
    }
    headers = {"Content-Type": "application/json"}

    response = requests.post(api_url, json=payload, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data.get("content", "No questions generated.")
    else:
        return f"Error: {response.text}"


# --- Translation API ---
@app.route("/translate_summary", methods=["POST"])
def translate_summary():
    data = request.json
    target_lang = data.get("language")
    summary = data.get("summary")

    if not target_lang or not summary:
        return jsonify({"error": "Missing data"}), 400

    try:
        translated_text = GoogleTranslator(source="auto", target=target_lang).translate(summary)
        return jsonify({"translated_summary": translated_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/translate_questions", methods=["POST"])
def translate_questions():
    data = request.json
    target_lang = data.get("language")
    questions = data.get("questions")

    if not target_lang or not questions:
        return jsonify({"error": "Missing data"}), 400

    try:
        translated_text = GoogleTranslator(source="auto", target=target_lang).translate(questions)
        return jsonify({"translated_questions": translated_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Home Route ---
@app.route("/", methods=["GET", "POST"])
def home():
    if "user" in session:
        return render_template("upload.html")  # Show upload if logged in
    return render_template("signin.html")  # Show sign-in if not logged in


# --- Upload & Process PDF ---
@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if "user" not in session:
        return redirect(url_for("signin"))

    if request.method == "POST":
        file = request.files.get("file")
        if file and file.filename:
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)

            if file.filename.lower().endswith(".pdf"):
                extracted_text = extract_text_from_pdf(filepath)
            else:
                extracted_text = extract_text_from_image(filepath)

            summary = summarize_text(extracted_text)  # AI-generated summary
            questions = generate_questions(extracted_text)  # AI-generated questions

            questions_html = markdown.markdown(questions)

            # Store in session for access in other routes
            session["extracted_text"] = extracted_text
            session["summary"] = summary
            session["questions"] = questions

            return render_template("result.html",
                                   extracted_text=extracted_text,
                                   questions=questions_html)
        return render_template("upload.html")


@app.route("/pdf-to-text")
def pdf_to_text():
    return render_template("pdf-to-text.html")  # Flask will find it inside `templates/`

@app.route("/ai-summary")
def ai_summary():
    summary = session.get("summary", "No summary available.")  # Retrieve AI-generated summary
    return render_template("ai-summary.html", summary=summary)


@app.route("/free-tool")
def free_tool():
    return render_template("free-tool.html")
@app.route("/multilingual-support")
def multilingual_support():
    return render_template("multilingual-support.html")
@app.route("/download-summary")
def download_summary():
    summary_text = session.get("summary", "No summary available.")  # Retrieve from session if available
    return render_template("download-summary.html", summary_text=summary_text)
@app.route("/extract-text", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    pdf_file = request.files["file"]
    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Invalid file type. Please upload a PDF."}), 400

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf_file.filename)
    pdf_file.save(file_path)

    # Extract text using PyMuPDF
    extracted_text = extract_text_from_pdf(file_path)

    return jsonify({"text": extracted_text})


if __name__ == "__main__":
    os.makedirs("uploads", exist_ok=True)
    app.run(debug=True, port=5001)