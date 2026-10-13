import os, json
import config

_GUIDES_CACHE = None

def get_all_guides():
    global _GUIDES_CACHE
    if _GUIDES_CACHE is not None:
        return _GUIDES_CACHE
    
    # Load from data/study_guides.json
    path = os.path.join(config.REPO_DATA_DIR, "study_guides.json")
    if not os.path.exists(path):
        path = os.path.join(config.DATA_DIR, "study_guides.json")
    
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _GUIDES_CACHE = json.load(f)
                return _GUIDES_CACHE
        except Exception:
            pass
    return {}

def get_guide(course_key):
    guides = get_all_guides()
    return guides.get(course_key)

def get_guide_file_path(course_key):
    guide = get_guide(course_key)
    if not guide:
        return None, None
    filename = guide["filename"]
    
    # Check static/guides first
    static_path = os.path.join(config.BASE, "static", "guides", filename)
    if os.path.exists(static_path):
        return static_path, filename
        
    # Check knowledge/guide
    orig_name = "Biostatistics Study Guide.pdf" if course_key == "biostatistics" else "PHP417_Pharmacoepidemiology_Practice_Questions.docx"
    guide_path = os.path.join(config.BASE, "knowledge", "guide", orig_name)
    if os.path.exists(guide_path):
        return guide_path, filename
        
    return None, None
