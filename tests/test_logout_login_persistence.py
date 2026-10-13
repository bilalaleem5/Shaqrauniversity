import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, db, account_store

def test_student_logout_and_relogin_flow():
    print("Testing student registration, logout, and relogin across serverless container restarts...")

    test_sid = "44556677"
    test_email = "ali_persistence@su.edu.sa"
    test_pw = "Password123"

    # Cleanup any previous test data
    db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))

    with app.app.test_client() as client:
        # Step 1: Student visits registration page to get CSRF
        r = client.get('/register')
        csrf = r.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        # Step 2: Student registers
        reg_resp = client.post('/register', data={
            'name': 'Ali Persistence',
            'student_id': test_sid,
            'email': test_email,
            'batch': '2024',
            'gender': 'male',
            'password': test_pw,
            'password2': test_pw,
            'csrf': csrf
        }, follow_redirects=False)

        assert reg_resp.status_code == 302, f"Expected 302 redirect after register, got {reg_resp.status_code}"
        assert '/courses' in reg_resp.headers['Location']
        print("[OK] 1. Student registered successfully and redirected to /courses")

        # Verify vault cookie was issued
        vault_cookie = client.get_cookie(account_store.VAULT_COOKIE_NAME)
        assert vault_cookie is not None, "Expected _su_v vault cookie to be set on registration response"
        print("[OK] 2. Client device vault cookie _su_v received:", vault_cookie.value[:30] + "...")

        # Step 3: Student accesses courses (works fine)
        courses_resp = client.get('/courses')
        assert courses_resp.status_code == 200
        print("[OK] 3. Student actively accessing courses while logged in")

        # Step 4: Student clicks LOGOUT
        logout_resp = client.get('/logout', follow_redirects=False)
        assert logout_resp.status_code == 302
        print("[OK] 4. Student logged out")

        # Verify active session is cleared
        courses_after_logout = client.get('/courses')
        assert courses_after_logout.status_code == 302
        assert '/login' in courses_after_logout.headers['Location']
        print("[OK] 5. Verified student is strictly logged out (cannot access /courses without login)")

        # Verify vault cookie is STILL preserved on browser after logout
        vault_cookie_after_logout = client.get_cookie(account_store.VAULT_COOKIE_NAME)
        assert vault_cookie_after_logout is not None, "Device vault cookie should NOT be deleted on logout"
        print("[OK] 6. Device vault cookie preserved on browser after logout")

        # Step 5: SIMULATE VERCEL SERVERLESS COLD START / FRESH CONTAINER
        # In a new container, the dynamic student was NOT in SQLite!
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))
        assert db.q("SELECT * FROM students WHERE email=?", (test_email,), one=True) is None
        print("[OK] 7. Emptied student from SQLite to simulate brand new serverless container")

        # Step 6: Student returns to /login on this new container and enters their EMAIL
        login_page = client.get('/login')
        csrf_login = login_page.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        login_resp = client.post('/login', data={
            'identifier': test_email,
            'password': test_pw,
            'csrf': csrf_login
        }, follow_redirects=False)

        assert login_resp.status_code == 302, f"Login failed! Status: {login_resp.status_code}. Response: {login_resp.data.decode('utf-8')[:300]}"
        assert '/courses' in login_resp.headers['Location']
        print("[OK] 8. Student LOGGED BACK IN SUCCESSFULLY using their email on fresh container!")

        # Verify student was automatically restored in SQLite with their REAL password hash
        restored = db.q("SELECT * FROM students WHERE email=?", (test_email,), one=True)
        assert restored is not None, "Student record was not restored in database"
        assert restored["pw_hash"] != "restored_session", "Password hash must be the real hash"
        print("[OK] 9. Student database record restored with real password hash in local container")

        # Step 7: Test login with WRONG password on cold start (must be rejected)
        client.get('/logout')
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))
        login_page2 = client.get('/login')
        csrf_login2 = login_page2.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        wrong_resp = client.post('/login', data={
            'identifier': test_email,
            'password': 'WrongPassword999',
            'csrf': csrf_login2
        })
        assert "Wrong student ID / email or password" in wrong_resp.data.decode('utf-8')
        print("[OK] 10. Wrong password correctly rejected")

        # Step 8: Test re-registering with matching password (must auto-login instead of error)
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))
        r_reg = client.get('/register')
        csrf_reg = r_reg.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]

        re_reg = client.post('/register', data={
            'name': 'Ali Persistence',
            'student_id': test_sid,
            'email': test_email,
            'batch': '2024',
            'gender': 'male',
            'password': test_pw,
            'password2': test_pw,
            'csrf': csrf_reg
        }, follow_redirects=False)
        assert re_reg.status_code == 302
        assert '/courses' in re_reg.headers['Location']
        print("[OK] 11. Re-registration with correct password smoothly signs student in")

        # Cleanup
        db.x("DELETE FROM students WHERE student_id=? OR email=?", (test_sid, test_email))
        print("\nALL PERSISTENCE AND RELOGIN TESTS PASSED FLAWLESSLY!")

if __name__ == '__main__':
    test_student_logout_and_relogin_flow()
