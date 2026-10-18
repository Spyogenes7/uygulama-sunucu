import os
import sys

# Auto-switch to virtual environment if current python lacks dependencies
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(BASE_DIR, 'venv', 'bin', 'python3')
if os.path.exists(venv_python) and sys.executable != venv_python:
    try:
        import flask
    except ImportError:
        os.execv(venv_python, [venv_python] + sys.argv)

import uuid
import socket
import webbrowser
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from werkzeug.utils import secure_filename
import database
import analyzer
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=STATIC_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB max

# Initialize database
database.init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory(STATIC_FOLDER, 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(STATIC_FOLDER, 'service-worker.js', mimetype='application/javascript')

@app.route('/api/papers', methods=['GET'])
def list_papers():
    quartile = request.args.get('quartile')
    search = request.args.get('search')
    papers = database.get_papers(filter_quartile=quartile, search=search)
    return jsonify({'status': 'success', 'papers': papers})

@app.route('/api/papers/<paper_id>', methods=['GET'])
def get_paper(paper_id):
    paper = database.get_paper_by_id(paper_id)
    if not paper:
        return jsonify({'status': 'error', 'message': 'Makale bulunamadı'}), 404
    return jsonify({'status': 'success', 'paper': paper})

@app.route('/api/papers/<paper_id>/pdf', methods=['GET'])
def get_paper_pdf(paper_id):
    paper = database.get_paper_by_id(paper_id)
    if not paper or not paper.get('pdf_filename'):
        return jsonify({'status': 'error', 'message': 'PDF bulunamadı'}), 404
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], paper['pdf_filename'])
    if not os.path.exists(pdf_path):
        return jsonify({'status': 'error', 'message': 'PDF dosyası diskte bulunamadı'}), 404
    return send_file(pdf_path, mimetype='application/pdf')

@app.route('/api/upload', methods=['POST'])
def upload_paper():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'Lütfen bir PDF dosyası seçin'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'Dosya seçilmedi'}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'status': 'error', 'message': 'Yalnızca PDF formatındaki tıbbi makaleler desteklenir'}), 400

    orig_name = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex[:10]}_{orig_name}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(save_path)

    try:
        # Extract PDF text and details
        pdf_data = analyzer.extract_pdf_data(save_path)
        
        # Query OpenAlex for accurate live metadata
        meta = analyzer.fetch_openalex_metadata(doi=pdf_data.get('doi'), title=pdf_data.get('title'))
        if not meta:
            meta = analyzer.extract_fallback_metadata(pdf_data)
            
        # Match journal in SCImago DB for Quartile (Q1, Q2, Q3, Q4)
        metrics = analyzer.lookup_scimago_metrics(meta.get('journal'), issn=meta.get('issn_l'))
        
        # Generate comprehensive medical summary
        api_key = request.form.get('gemini_api_key') or os.environ.get('GEMINI_API_KEY')
        abstract_content = meta.get('abstract') or pdf_data.get('abstract') or ''
        summary = analyzer.generate_medical_summary(abstract_content, pdf_data.get('full_text', ''), api_key=api_key)
        
        paper_id = database.save_paper({
            'title': meta.get('title') or orig_name,
            'authors': meta.get('authors') or '',
            'journal': metrics.get('matched_journal') or meta.get('journal') or 'Bilinmeyen Dergi',
            'issn': meta.get('issn_l') or '',
            'publication_year': meta.get('year') or 2024,
            'citation_count': meta.get('citations') or 0,
            'quartile': metrics.get('quartile') or 'Q1',
            'sjr': metrics.get('sjr') or 0.0,
            'h_index': metrics.get('h_index') or 0,
            'field_name': metrics.get('field_name') or meta.get('field_name') or 'Tıp ve Sağlık Bilimleri',
            'doi': meta.get('doi') or pdf_data.get('doi') or '',
            'pdf_filename': unique_filename,
            'summary': summary,
            'abstract': abstract_content
        })
        
        full_paper = database.get_paper_by_id(paper_id)
        return jsonify({'status': 'success', 'paper': full_paper})
    except Exception as e:
        print(f"Upload processing error: {e}")
        return jsonify({'status': 'error', 'message': f"Makale analiz edilirken bir hata oluştu: {str(e)}"}), 500

@app.route('/api/add_by_doi', methods=['POST'])
def add_by_doi():
    data = request.get_json() or {}
    doi = data.get('doi', '').strip()
    title = data.get('title', '').strip()
    
    if not doi and not title:
        return jsonify({'status': 'error', 'message': 'Lütfen geçerli bir DOI veya Makale Başlığı girin'}), 400

    try:
        meta = analyzer.fetch_openalex_metadata(doi=doi if doi else None, title=title if title else None)
        if not meta:
            return jsonify({'status': 'error', 'message': 'Belirtilen DOI veya başlıkla makale bulunamadı'}), 404
            
        metrics = analyzer.lookup_scimago_metrics(meta.get('journal'), issn=meta.get('issn_l'))
        summary = analyzer.generate_medical_summary(meta.get('abstract') or '')
        
        paper_id = database.save_paper({
            'title': meta.get('title'),
            'authors': meta.get('authors'),
            'journal': metrics.get('matched_journal') or meta.get('journal'),
            'issn': meta.get('issn_l'),
            'publication_year': meta.get('year'),
            'citation_count': meta.get('citations'),
            'quartile': metrics.get('quartile'),
            'sjr': metrics.get('sjr'),
            'h_index': metrics.get('h_index'),
            'field_name': metrics.get('field_name'),
            'doi': meta.get('doi') or doi,
            'pdf_filename': '', # Metadata only without local PDF
            'summary': summary,
            'abstract': meta.get('abstract') or ''
        })
        
        full_paper = database.get_paper_by_id(paper_id)
        return jsonify({'status': 'success', 'paper': full_paper})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Hata: {str(e)}"}), 500

@app.route('/api/papers/<paper_id>/notes', methods=['POST'])
def save_notes(paper_id):
    data = request.get_json() or {}
    content = data.get('content', '')
    database.update_paper_notes(paper_id, content)
    return jsonify({'status': 'success', 'message': 'Notlar kaydedildi'})

@app.route('/api/papers/<paper_id>/annotations', methods=['POST'])
def add_annot(paper_id):
    data = request.get_json() or {}
    annot_id = database.add_annotation(paper_id, data)
    return jsonify({'status': 'success', 'id': annot_id})

@app.route('/api/annotations/<annot_id>', methods=['DELETE'])
def delete_annot(annot_id):
    database.delete_annotation(annot_id)
    return jsonify({'status': 'success', 'message': 'Not/Vurgu silindi'})

@app.route('/api/papers/<paper_id>/toggle_favorite', methods=['POST'])
def toggle_fav(paper_id):
    fav = database.toggle_favorite(paper_id)
    return jsonify({'status': 'success', 'favorite': fav})

@app.route('/api/papers/<paper_id>/ai_summarize', methods=['POST'])
def ai_summarize(paper_id):
    paper = database.get_paper_by_id(paper_id)
    if not paper:
        return jsonify({'status': 'error', 'message': 'Makale bulunamadı'}), 404
        
    data = request.get_json() or {}
    api_key = data.get('api_key') or os.environ.get('GEMINI_API_KEY')
    custom_prompt = data.get('custom_prompt')
    
    # Read text if PDF exists
    full_text = ""
    if paper.get('pdf_filename'):
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], paper['pdf_filename'])
        if os.path.exists(pdf_path):
            try:
                pdf_data = analyzer.extract_pdf_data(pdf_path)
                full_text = pdf_data.get('full_text', '')
            except Exception:
                pass
                
    abstract_content = paper.get('abstract') or ''
    summary = analyzer.generate_medical_summary(abstract_content, full_text, api_key=api_key, custom_prompt=custom_prompt)
    
    # Update paper with new summary
    paper['summary'] = summary
    database.save_paper(paper)
    return jsonify({'status': 'success', 'summary': summary})

@app.route('/api/papers/<paper_id>/reanalyze', methods=['POST'])
def reanalyze_paper(paper_id):
    paper = database.get_paper_by_id(paper_id)
    if not paper:
        return jsonify({'status': 'error', 'message': 'Makale bulunamadı'}), 404
        
    full_text = ""
    extracted_abs = paper.get('abstract') or ''
    if paper.get('pdf_filename'):
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], paper['pdf_filename'])
        if os.path.exists(pdf_path):
            try:
                pdf_data = analyzer.extract_pdf_data(pdf_path)
                full_text = pdf_data.get('full_text', '')
                if not extracted_abs or 'ncbi kitaplığı' in extracted_abs.lower():
                    extracted_abs = pdf_data.get('abstract', '')
            except Exception:
                pass
                
    summary = analyzer.generate_medical_summary(extracted_abs, full_text)
    paper['summary'] = summary
    paper['abstract'] = extracted_abs
    database.save_paper(paper)
    return jsonify({'status': 'success', 'summary': summary, 'paper': paper})

@app.route('/api/papers/<paper_id>', methods=['DELETE'])
def delete_paper(paper_id):
    filename = database.delete_paper(paper_id)
    if filename:
        fpath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    return jsonify({'status': 'success', 'message': 'Makale başarıyla silindi'})

@app.route('/api/stats', methods=['GET'])
def get_library_stats():
    stats = database.get_stats()
    return jsonify({'status': 'success', 'stats': stats})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    
    # Check if port is already running
    def is_port_in_use(p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', p))
                return False
            except OSError:
                return True

    if is_port_in_use(port):
        print(f"==================================================")
        print(f" 🩺 MedPaper AI — Sunucu Zaten Arka Planda Aktif!")
        print(f" 🌐 Uygulamaya Git: http://localhost:{port}")
        print(f"==================================================")
        try:
            # Silence osascript errors in sandbox
            devnull = open(os.devnull, 'w')
            old_err = os.dup(2)
            os.dup2(devnull.fileno(), 2)
            webbrowser.open(f"http://localhost:{port}")
            os.dup2(old_err, 2)
            os.close(old_err)
            devnull.close()
        except Exception:
            pass
        sys.exit(0)

    print(f"==================================================")
    print(f" MedPaper AI - Tıbbi Makale & Metrik Analizörü")
    print(f" Sunucu başlatıldı: http://localhost:{port}")
    print(f"==================================================")
    try:
        devnull = open(os.devnull, 'w')
        old_err = os.dup(2)
        os.dup2(devnull.fileno(), 2)
        webbrowser.open(f"http://localhost:{port}")
        os.dup2(old_err, 2)
        os.close(old_err)
        devnull.close()
    except Exception:
        pass
    app.run(host='0.0.0.0', port=port, debug=False)


