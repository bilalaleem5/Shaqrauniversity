# Shaqra AI Course Tutor & Faculty Intelligence Platform

Intelligent course companion strictly grounded in official university lecture slides and syllabi for Shaqra University (College of Pharmacy).

---

## 🌟 Key New Features & Capabilities

### 1. Modern Portal Selection (`/`)
- **Role Selection Landing Page:** Clean portal selection between **Student Learning Portal** and **Faculty Dashboard**.
- **Student Authentication:** Students can **Sign In** or **Register** a new account (validated university ID, batch, and email).
- **Faculty Authentication:** Faculty portal has **Sign In only** (credentials are managed by the administrator).

### 2. Course Knowledge Base Management (`/teacher/knowledge`)
- **Per-Course Repository:** Switch between any active course with one click.
- **Upload Lecture Materials:** Drag-and-drop or browse multiple files (`.pdf`, `.docx`, `.pptx`, `.txt`, `.md`).
- **Auto-Chunking & Embedding:** Files are automatically extracted, chunked, and embedded into vector storage for immediate AI tutor retrieval.
- **File Management:** View document sizes, delete outdated slides, or trigger a full course re-index.

### 3. Add 3rd, 4th, and Additional Courses (`/teacher/courses`)
- **Dynamic Course Creation:** Super Admin can add new academic courses (e.g. Pharmaceutical Analysis, Pharmacology, Medicinal Chemistry).
- **Instant Integration:** Automatically provisions a dedicated knowledge directory and lists the course in the student catalog.

### 4. Faculty & Instructor Account Provisioning (`/teacher/teachers`)
- **Multi-Instructor Support:** Super Admin can provision accounts for fellow professors or teaching assistants.
- **Super Admin Protection:** The primary administrator retains exclusive control; secondary instructors cannot delete accounts or alter system privileges.

### 5. Anonymous Student Feedback Channel (`/feedback` & `/teacher/feedback`)
- **Student Side:** Students can report issues with lecture notes, question clarity, AI answers, or platform bugs.
- **100% Anonymous:** Student name, email, and student ID are **never** attached to feedback submissions.
- **Faculty Side:** Faculty can review anonymous feedback cards with timestamps and category badges, ensuring continuous curriculum improvement.

---

## 🔑 Default Credentials

### Primary Administrator / Faculty:
- **URL:** `http://localhost:5000/teacher/login`
- **Username:** `teacher`
- **Password:** `Shaqra@Teacher2026`
*(Change password after first login in Settings).*

### Student Portal:
- **URL:** `http://localhost:5000/login`
- Students can log in or register freely via `/register`.

---

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set OPENAI_API_KEY in .env for GPT-4o-mini and text-embedding-3-small

# 3. Start the application
python app.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🧪 Testing

```bash
python tests/test_all.py
```
Runs comprehensive test suites covering authentication, RAG retrieval, quiz generation, course management, and feedback.
