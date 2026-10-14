import sys, os, json
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, db, account_store
from werkzeug.security import check_password_hash

def test_full_student_relogin_and_chat_history():
    print("\n--- Starting Comprehensive Student Relogin & Chat History Test ---")

    test_sid = "44109999"
    test_email = "s_history_test@su.edu.sa"
    test_pw = "Password123"

    # 1. Clean up old test data
    db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))

    with app.app.test_client() as client:
        # Step 1: Register new student
        r = client.get('/register')
        csrf = r.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        reg_resp = client.post('/register', data={
            'name': 'Test Student History',
            'student_id': test_sid,
            'email': test_email,
            'batch': '2024',
            'gender': 'male',
            'password': test_pw,
            'password2': test_pw,
            'csrf': csrf
        }, follow_redirects=False)

        assert reg_resp.status_code == 302
        assert '/courses' in reg_resp.headers['Location']
        print("[OK] 1. Student registered successfully")

        # Step 2: Open chat page for biostatistics
        chat_resp = client.get('/chat/biostatistics')
        assert chat_resp.status_code == 200
        html = chat_resp.data.decode('utf-8')
        assert 'initial_history = []' in html or 'const serverHistory = []' in html
        print("[OK] 2. Opened chat page (empty initial history as expected)")

        # Step 3: Student asks a question
        csrf_chat = html.split('name="csrf" content="')[1].split('"')[0]
        msg_resp = client.post('/api/chat/biostatistics',
            headers={'X-CSRF': csrf_chat, 'Content-Type': 'application/json'},
            data=json.dumps({'message': 'What is the sample mean in biostatistics?'})
        )
        assert msg_resp.status_code == 200
        msg_data = msg_resp.get_json()
        assert 'answer' in msg_data
        print("[OK] 3. Student asked question, received tutor answer")

        # Verify message was saved to DB with student_pk
        stu = db.q("SELECT id FROM students WHERE student_id=?", (test_sid,), one=True)
        assert stu is not None
        saved_msgs = db.q("SELECT * FROM messages WHERE student_pk=? AND course='biostatistics'", (stu["id"],))
        assert len(saved_msgs) == 1
        assert saved_msgs[0]["question"] == 'What is the sample mean in biostatistics?'
        print("[OK] 4. Message successfully verified in database messages table")

        # Step 4: Student clicks LOGOUT
        logout_resp = client.get('/logout', follow_redirects=False)
        assert logout_resp.status_code == 302
        print("[OK] 5. Student logged out")

        # Verify courses cannot be accessed when logged out
        courses_check = client.get('/courses')
        assert courses_check.status_code == 302
        print("[OK] 6. Verified courses protected after logout")

        # Step 5: Student logs back in with email & password
        login_page = client.get('/login')
        csrf_login = login_page.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        login_resp = client.post('/login', data={
            'identifier': test_email,
            'password': test_pw,
            'csrf': csrf_login
        }, follow_redirects=False)

        assert login_resp.status_code == 302, f"Expected 302 on login, got {login_resp.status_code}"
        assert '/courses' in login_resp.headers['Location']
        print("[OK] 7. Student successfully logged back in!")

        # Step 6: Student returns to /chat/biostatistics - PAST CHAT HISTORY MUST BE THERE!
        chat_return = client.get('/chat/biostatistics')
        assert chat_return.status_code == 200
        chat_html = chat_return.data.decode('utf-8')
        assert 'What is the sample mean in biostatistics?' in chat_html, "Previous question must be present in serverHistory template!"
        assert 'const serverHistory =' in chat_html
        print("[OK] 8. VERIFIED: Student past chat history is loaded and present on re-login!")

        # Step 7: Test /api/chat/biostatistics/history endpoint
        hist_api = client.get('/api/chat/biostatistics/history')
        assert hist_api.status_code == 200
        hist_data = hist_api.get_json()
        assert len(hist_data.get('history', [])) == 1
        assert hist_data['history'][0]['question'] == 'What is the sample mean in biostatistics?'
        print("[OK] 9. VERIFIED: /api/chat/biostatistics/history returns correct history list")

        # Step 8: Test client sync endpoint (simulating local cache restoring to fresh container)
        new_cached_msg = {
            'question': 'How to calculate variance?',
            'answer': 'Variance measures dispersion...',
            'sources': ['Slide 5'],
            'topic': 'Descriptive Stats'
        }
        sync_resp = client.post('/api/chat/biostatistics/sync',
            headers={'X-CSRF': csrf_login, 'Content-Type': 'application/json'},
            data=json.dumps({'messages': [new_cached_msg]})
        )
        assert sync_resp.status_code == 200
        synced_msgs = db.q("SELECT * FROM messages WHERE student_pk=? AND course='biostatistics' ORDER BY id ASC", (stu["id"],))
        assert len(synced_msgs) == 2
        print("[OK] 10. VERIFIED: Offline/local client sync seamlessly restores messages to DB")

        # Step 9: Test clear chat
        clear_resp = client.post('/api/chat/biostatistics/clear',
            headers={'X-CSRF': csrf_login, 'Content-Type': 'application/json'},
            data=json.dumps({})
        )
        assert clear_resp.status_code == 200
        cleared_msgs = db.q("SELECT * FROM messages WHERE student_pk=? AND course='biostatistics'", (stu["id"],))
        assert len(cleared_msgs) == 0
        print("[OK] 11. VERIFIED: Clear chat clears database messages for student")

        # Step 10: Test Self-Healing of corrupted 'restored_session' pw_hash records
        corrupt_sid = "99887766"
        corrupt_email = "corrupt_stu@su.edu.sa"
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (corrupt_sid, corrupt_email))
        db.x("INSERT INTO students(student_id, email, name, batch, pw_hash) VALUES(?,?,?,?,?)",
             (corrupt_sid, corrupt_email, "Corrupt Student", "2024", "restored_session"))
        
        # Student tries to log in with their intended password
        client.get('/logout')
        l_page = client.get('/login')
        csrf_l = l_page.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]
        heal_resp = client.post('/login', data={
            'identifier': corrupt_email,
            'password': 'HealedPassword123',
            'csrf': csrf_l
        }, follow_redirects=False)
        assert heal_resp.status_code == 302, "Corrupted record must be self-healed and logged in!"
        
        # Verify pw_hash is now real and checkable
        healed_stu = db.q("SELECT * FROM students WHERE email=?", (corrupt_email,), one=True)
        assert check_password_hash(healed_stu["pw_hash"], "HealedPassword123")
        print("[OK] 12. VERIFIED: Corrupted 'restored_session' placeholder accounts automatically self-heal on login!")

        # Step 11: Test Self-Healing on re-register
        corrupt_sid2 = "88776655"
        corrupt_email2 = "corrupt_reg@su.edu.sa"
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (corrupt_sid2, corrupt_email2))
        db.x("INSERT INTO students(student_id, email, name, batch, pw_hash) VALUES(?,?,?,?,?)",
             (corrupt_sid2, corrupt_email2, "Corrupt Student 2", "2024", "restored_session"))
        
        client.get('/logout')
        r_page = client.get('/register')
        csrf_r = r_page.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]
        re_reg_resp = client.post('/register', data={
            'name': 'Corrupt Student 2',
            'student_id': corrupt_sid2,
            'email': corrupt_email2,
            'batch': '2024',
            'password': 'NewPassword999',
            'password2': 'NewPassword999',
            'csrf': csrf_r
        }, follow_redirects=False)
        assert re_reg_resp.status_code == 302, "Corrupted record must allow re-registration to claim password!"
        healed_stu2 = db.q("SELECT * FROM students WHERE email=?", (corrupt_email2,), one=True)
        assert check_password_hash(healed_stu2["pw_hash"], "NewPassword999")
        print("[OK] 13. VERIFIED: Corrupted accounts allow re-registration to claim and set real password!")

        # Clean up
        db.x("DELETE FROM students WHERE student_id IN (?, ?, ?)", (test_sid, corrupt_sid, corrupt_sid2))
        print("\nALL STUDENT RELOGIN AND CHAT HISTORY TESTS PASSED PERFECTLY!\n")

if __name__ == '__main__':
    test_full_student_relogin_and_chat_history()
