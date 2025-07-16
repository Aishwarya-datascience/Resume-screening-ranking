from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
import os
import fitz  # PyMuPDF
import docx
import re
import json
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ------------------- Utility Functions -------------------

def extract_text(file_path):
    text = ''
    if file_path.endswith('.pdf'):
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
    elif file_path.endswith('.docx'):
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + '\n'
    elif file_path.endswith('.txt'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    return text.lower()

def extract_email(text):
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else 'Not Found'

def calc_score(content, job_title, job_desc, skills):
    title_score = 20 if job_title in content else 15 if job_title.lower() in content else 5
    job_tokens = set(job_desc.split())
    resume_tokens = set(content.split())
    overlap = len(job_tokens & resume_tokens)
    jd_score = min((overlap / len(job_tokens)) * 30, 30) if job_tokens else 0
    matched = sum(1 for skill in skills if skill.strip().lower() in content)
    skill_score = min(matched * 5, 50)
    total_score = min(round(title_score + jd_score + skill_score), 100)
    return total_score, round(title_score), round(jd_score), round(skill_score)

def save_user(user):
    users = []
    if os.path.exists('users.json'):
        with open('users.json', 'r') as f:
            try:
                users = json.load(f)
            except:
                users = []
    users.append(user)
    with open('users.json', 'w') as f:
        json.dump(users, f, indent=4)

def load_users():
    if os.path.exists('users.json'):
        with open('users.json', 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

# ------------------- Routes -------------------

@app.route('/')
def home():
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        users = load_users()
        user = next((u for u in users if u['email'] == email), None)
        if user and check_password_hash(user['password'], password):
            session['user'] = user
            return redirect('/index')
        else:
            flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        company = request.form['company']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        save_user({"name": name, "company": company, "email": email, "password": password})
        flash("Signup successful. Please login.", "success")
        return redirect('/login')
    return render_template('signup.html')

@app.route('/index', methods=['GET', 'POST'])
def index():
    resumes, job_title, job_desc, skills = [], '', '', ''
    min_score = 50

    if request.method == 'POST':
        job_title = request.form.get('job_title', '').lower()
        job_desc = request.form.get('job_desc', '').lower()
        skills = request.form.get('skills', '').lower()
        min_score = int(request.form.get('min_score', 50))
        skill_list = skills.split(',')
        jd_tokens = set([s.strip().lower() for s in skill_list if s.strip()])

        uploaded_files = request.files.getlist('resumes')
        for file in uploaded_files:
            try:
                filename = file.filename
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                content = extract_text(filepath)
                score, title_score, jd_score, skill_score = calc_score(content, job_title, job_desc, skill_list)
                email = extract_email(content)
                matched_skills = [skill for skill in jd_tokens if skill in content]

                resumes.append({
                    'name': filename,
                    'email': email,
                    'score': score,
                    'title_score': title_score,
                    'jd_score': jd_score,
                    'skill_score': skill_score,
                    'skills': ', '.join(matched_skills) if matched_skills else 'None',
                    'file': filename
                })
            except Exception as e:
                print(f"[ERROR] Failed to process {file.filename}: {e}")
                continue

        resumes.sort(key=lambda x: x['score'], reverse=True)
        session['ranked'] = resumes
        session['job_title'] = job_title
        session['job_desc'] = job_desc
        session['skills'] = skills
        session['min_score'] = min_score
    else:
        resumes = session.get('ranked', [])
        job_title = session.get('job_title', '')
        job_desc = session.get('job_desc', '')
        skills = session.get('skills', '')
        min_score = session.get('min_score', 50)

    return render_template('index.html', resumes=resumes, job_title=job_title,
                           job_desc=job_desc, skills=skills, min_score=min_score)

@app.route('/candidate/<int:idx>')
def candidate(idx):
    resumes = session.get('ranked', [])
    if 0 <= idx < len(resumes):
        return render_template('candidate.html', resume=resumes[idx], idx=idx, min_score=session.get('min_score', 50))
    return redirect('/index')

@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), mimetype='application/pdf')

@app.route('/download_all')
def download_all():
    import io
    from zipfile import ZipFile
    resumes = session.get('ranked', [])
    min_score = session.get('min_score', 50)
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, 'w') as zip_file:
        for r in resumes:
            if r['score'] >= min_score:
                path = os.path.join(app.config['UPLOAD_FOLDER'], r['file'])
                if os.path.exists(path):
                    zip_file.write(path, arcname=r['file'])
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name='high_scores.zip')

@app.route('/reject', methods=['POST'])
def reject():
    resumes = session.get('ranked', [])
    min_score = int(request.form.get('min_score', 50))
    session['ranked'] = [r for r in resumes if r['score'] >= min_score]
    return redirect('/index')

# ------------------- Run App -------------------

if __name__ == '__main__':
    app.run(debug=True)
