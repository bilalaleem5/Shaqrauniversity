import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, db

def test_session_recovery():
    db.x("DELETE FROM students WHERE student_id IN ('44990011', '44990022')")
    with app.app.test_client() as c:
        # Get CSRF
        r = c.get('/login')
        html = r.data.decode('utf-8')
        csrf = html.split('name="csrf" value="')[1].split('"')[0]

        # Register
        reg = c.post('/register', data={
            'name': 'Serverless Student',
            'student_id': '44990011',
            'email': 'serverless@su.edu.sa',
            'batch': '2025',
            'gender': 'male',
            'password': 'Password123',
            'password2': 'Password123',
            'csrf': csrf
        }, follow_redirects=True)
        print('1. Register response status:', reg.status_code)

        # Simulate cold-start on a new container where DB does not have this student:
        db.x("DELETE FROM students WHERE student_id='44990011'")
        assert db.q("SELECT * FROM students WHERE student_id='44990011'", one=True) is None
        print('2. Emptied student from DB to simulate fresh container')

        # Student accesses courses on this new container
        crs = c.get('/courses')
        print('3. /courses response status:', crs.status_code)
        assert crs.status_code == 200, f"Expected 200, got {crs.status_code} (student was logged out)"

        # Verify student was automatically restored in DB for foreign keys & chat/quiz
        restored = db.q("SELECT student_id, name FROM students WHERE student_id='44990011'", one=True)
        print('4. Student restored in SQLite:', dict(restored) if restored else None)
        assert restored is not None, "Student was not restored"

        # Cleanup test student
        db.x("DELETE FROM students WHERE student_id='44990011'")
        print("ALL SERVERLESS SESSION TESTS PASSED SUCCESSFULLY!")

def test_chat_assets():
    with app.app.test_client() as c:
        # Re-register for chat page check
        r = c.get('/login')
        csrf = r.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]
        c.post('/register', data={
            'name': 'Chat Test Student',
            'student_id': '44990022',
            'email': 'chattest@su.edu.sa',
            'batch': '2024',
            'gender': 'female',
            'password': 'Password123',
            'password2': 'Password123',
            'csrf': csrf
        }, follow_redirects=True)

        chat_page = c.get('/chat/pharmacoepi')
        assert chat_page.status_code == 200
        html = chat_page.data.decode('utf-8')
        assert 'katex.min.js' in html, 'KaTeX JS missing'
        assert 'katex.min.css' in html, 'KaTeX CSS missing'
        assert 'marked.min.js' in html, 'Marked.js missing'
        assert 'renderContent' in html, 'renderContent function missing'
        print("CHAT ASSETS AND RENDERING TESTS PASSED SUCCESSFULLY!")
        db.x("DELETE FROM students WHERE student_id='44990022'")

if __name__ == '__main__':
    test_session_recovery()
    test_chat_assets()
