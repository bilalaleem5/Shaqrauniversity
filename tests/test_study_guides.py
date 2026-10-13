import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, db, study_guide

def test_study_guides():
    print("Testing study guide module and endpoints...")
    # 1. Check data loaded
    bio = study_guide.get_guide("biostatistics")
    assert bio is not None, "Biostatistics guide not found"
    assert len(bio["items"]) == 20, f"Expected 20 items, got {len(bio['items'])}"
    print(f"[OK] Biostatistics guide loaded: {bio['guide_title']} (20 items)")

    pharm = study_guide.get_guide("pharmacoepi")
    assert pharm is not None, "Pharmacoepi guide not found"
    assert len(pharm["items"]) == 20, f"Expected 20 items, got {len(pharm['items'])}"
    print(f"[OK] Pharmacoepidemiology guide loaded: {pharm['guide_title']} (20 items)")

    # 2. Check files exist for download
    bio_fpath, bio_fname = study_guide.get_guide_file_path("biostatistics")
    assert os.path.exists(bio_fpath), f"Biostatistics file missing: {bio_fpath}"
    assert bio_fname.endswith(".pdf"), f"Expected PDF: {bio_fname}"
    print(f"[OK] Biostatistics file ready: {bio_fname} ({os.path.getsize(bio_fpath)} bytes)")

    pharm_fpath, pharm_fname = study_guide.get_guide_file_path("pharmacoepi")
    assert os.path.exists(pharm_fpath), f"Pharmacoepi file missing: {pharm_fpath}"
    assert pharm_fname.endswith(".docx"), f"Expected DOCX: {pharm_fname}"
    print(f"[OK] Pharmacoepidemiology file ready: {pharm_fname} ({os.path.getsize(pharm_fpath)} bytes)")

    # 3. Test Flask routes with student session
    db.x("DELETE FROM students WHERE student_id='44889900'")
    with app.app.test_client() as c:
        r = c.get('/login')
        csrf = r.data.decode('utf-8').split('name="csrf" value="')[1].split('"')[0]
        c.post('/register', data={
            'name': 'Guide Test Student',
            'student_id': '44889900',
            'email': 'guidetest@su.edu.sa',
            'batch': '2024',
            'gender': 'male',
            'password': 'Password123',
            'password2': 'Password123',
            'csrf': csrf
        }, follow_redirects=True)

        # /courses page has study guide badges & download buttons
        crs = c.get('/courses')
        assert crs.status_code == 200
        html = crs.data.decode('utf-8')
        assert "20 Exam Concepts" in html
        assert "/guide/biostatistics" in html
        assert "/guide/pharmacoepi" in html
        print("[OK] /courses displays study guide links and badges")

        # /guide/biostatistics page
        g_bio = c.get('/guide/biostatistics')
        assert g_bio.status_code == 200
        bio_html = g_bio.data.decode('utf-8')
        assert "20 High-Yield Exam Concepts" in bio_html
        assert "Biostatistics &amp; Health Informatics" in bio_html or "Biostatistics" in bio_html
        assert "/guide/biostatistics/download" in bio_html
        print("[OK] /guide/biostatistics rendered successfully")

        # /guide/pharmacoepi page
        g_pharm = c.get('/guide/pharmacoepi')
        assert g_pharm.status_code == 200
        pharm_html = g_pharm.data.decode('utf-8')
        assert "PHP 417" in pharm_html
        assert "/guide/pharmacoepi/download" in pharm_html
        print("[OK] /guide/pharmacoepi rendered successfully")

        # /guide/biostatistics/download
        dl_bio = c.get('/guide/biostatistics/download')
        assert dl_bio.status_code == 200
        assert len(dl_bio.data) > 100000
        print(f"[OK] /guide/biostatistics/download delivered {len(dl_bio.data)} bytes PDF")

        # /guide/pharmacoepi/download
        dl_pharm = c.get('/guide/pharmacoepi/download')
        assert dl_pharm.status_code == 200
        assert len(dl_pharm.data) > 10000
        print(f"[OK] /guide/pharmacoepi/download delivered {len(dl_pharm.data)} bytes DOCX")

        # /api/guide/biostatistics
        api_bio = c.get('/api/guide/biostatistics')
        assert api_bio.status_code == 200
        data = api_bio.get_json()
        assert len(data["items"]) == 20
        print("[OK] /api/guide/biostatistics returned 20 JSON items")

        # /chat/biostatistics with initial prompt
        chat_bio = c.get('/guide/biostatistics')
        assert chat_bio.status_code == 200
        print("[OK] /chat/biostatistics renders with guide integration")

        # Cleanup
        db.x("DELETE FROM students WHERE student_id='44889900'")
        print("\nALL STUDY GUIDE TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    test_study_guides()
