import sqlite3
import os
import json
import uuid
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'papers.db')

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Papers table
    c.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT,
            journal TEXT,
            issn TEXT,
            publication_year INTEGER,
            citation_count INTEGER DEFAULT 0,
            quartile TEXT,
            sjr REAL,
            h_index INTEGER,
            field_name TEXT,
            doi TEXT,
            pdf_filename TEXT,
            summary_json TEXT,
            abstract TEXT,
            favorite INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')
    
    # Notes table (Side notebook / kenar notları)
    c.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            paper_id TEXT,
            content TEXT,
            updated_at TIMESTAMP,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        )
    ''')
    
    # Annotations table (PDF highlights & sticky notes / üstüne notlar)
    c.execute('''
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            paper_id TEXT,
            page_num INTEGER,
            type TEXT,
            color TEXT,
            rects_json TEXT,
            x REAL,
            y REAL,
            selected_text TEXT,
            note_text TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(publication_year)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_papers_quartile ON papers(quartile)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_notes_paper ON notes(paper_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_annot_paper ON annotations(paper_id)')
    
    conn.commit()
    conn.close()

def save_paper(paper_data):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    paper_id = paper_data.get('id') or str(uuid.uuid4())
    
    c.execute('''
        INSERT OR REPLACE INTO papers 
        (id, title, authors, journal, issn, publication_year, citation_count,
         quartile, sjr, h_index, field_name, doi, pdf_filename, summary_json,
         abstract, favorite, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        paper_id,
        paper_data.get('title', 'Başlıksız Makale'),
        paper_data.get('authors', ''),
        paper_data.get('journal', 'Bilinmeyen Dergi'),
        paper_data.get('issn', ''),
        paper_data.get('publication_year'),
        paper_data.get('citation_count', 0),
        paper_data.get('quartile', 'N/A'),
        paper_data.get('sjr', 0.0),
        paper_data.get('h_index', 0),
        paper_data.get('field_name', 'Tıp / Sağlık Bilimleri'),
        paper_data.get('doi', ''),
        paper_data.get('pdf_filename', ''),
        json.dumps(paper_data.get('summary', {}), ensure_ascii=False) if isinstance(paper_data.get('summary'), dict) else paper_data.get('summary_json', '{}'),
        paper_data.get('abstract', ''),
        paper_data.get('favorite', 0),
        paper_data.get('tags', ''),
        paper_data.get('created_at', now),
        now
    ))
    
    # Initialize empty notes record if not exists
    c.execute('SELECT id FROM notes WHERE paper_id = ?', (paper_id,))
    if not c.fetchone():
        c.execute('''
            INSERT INTO notes (id, paper_id, content, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (str(uuid.uuid4()), paper_id, '', now))
        
    conn.commit()
    conn.close()
    return paper_id

def get_papers(filter_quartile=None, search=None):
    conn = get_connection()
    c = conn.cursor()
    query = 'SELECT * FROM papers WHERE 1=1'
    params = []
    
    if filter_quartile and filter_quartile != 'ALL':
        query += ' AND quartile = ?'
        params.append(filter_quartile)
        
    if search:
        query += ' AND (title LIKE ? OR journal LIKE ? OR authors LIKE ? OR tags LIKE ?)'
        wildcard = f'%{search}%'
        params.extend([wildcard, wildcard, wildcard, wildcard])
        
    query += ' ORDER BY created_at DESC'
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_paper_by_id(paper_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM papers WHERE id = ?', (paper_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    data = dict(row)
    
    # Get notes
    c.execute('SELECT content FROM notes WHERE paper_id = ?', (paper_id,))
    note_row = c.fetchone()
    data['notes'] = note_row['content'] if note_row else ''
    
    # Get annotations
    c.execute('SELECT * FROM annotations WHERE paper_id = ? ORDER BY page_num, created_at', (paper_id,))
    data['annotations'] = [dict(a) for a in c.fetchall()]
    
    if data.get('summary_json'):
        try:
            data['summary'] = json.loads(data['summary_json'])
        except Exception:
            data['summary'] = {}
            
    conn.close()
    return data

def update_paper_notes(paper_id, content):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('SELECT id FROM notes WHERE paper_id = ?', (paper_id,))
    row = c.fetchone()
    if row:
        c.execute('UPDATE notes SET content = ?, updated_at = ? WHERE paper_id = ?', (content, now, paper_id))
    else:
        c.execute('INSERT INTO notes (id, paper_id, content, updated_at) VALUES (?, ?, ?, ?)',
                  (str(uuid.uuid4()), paper_id, content, now))
    conn.commit()
    conn.close()

def add_annotation(paper_id, annot_data):
    conn = get_connection()
    c = conn.cursor()
    annot_id = annot_data.get('id') or str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    c.execute('''
        INSERT INTO annotations 
        (id, paper_id, page_num, type, color, rects_json, x, y, selected_text, note_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        annot_id,
        paper_id,
        annot_data.get('page_num', 1),
        annot_data.get('type', 'highlight'),
        annot_data.get('color', 'yellow'),
        json.dumps(annot_data.get('rects', [])),
        annot_data.get('x', 0),
        annot_data.get('y', 0),
        annot_data.get('selected_text', ''),
        annot_data.get('note_text', ''),
        now
    ))
    conn.commit()
    conn.close()
    return annot_id

def delete_annotation(annot_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM annotations WHERE id = ?', (annot_id,))
    conn.commit()
    conn.close()

def toggle_favorite(paper_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE papers SET favorite = 1 - favorite WHERE id = ?', (paper_id,))
    c.execute('SELECT favorite FROM papers WHERE id = ?', (paper_id,))
    res = c.fetchone()
    conn.commit()
    conn.close()
    return res['favorite'] if res else 0

def delete_paper(paper_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT pdf_filename FROM papers WHERE id = ?', (paper_id,))
    row = c.fetchone()
    filename = row['pdf_filename'] if row else None
    
    c.execute('DELETE FROM annotations WHERE paper_id = ?', (paper_id,))
    c.execute('DELETE FROM notes WHERE paper_id = ?', (paper_id,))
    c.execute('DELETE FROM papers WHERE id = ?', (paper_id,))
    conn.commit()
    conn.close()
    return filename

def get_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as total FROM papers')
    total = c.fetchone()['total']
    
    c.execute('SELECT quartile, COUNT(*) as count FROM papers GROUP BY quartile')
    quartiles = {r['quartile']: r['count'] for r in c.fetchall()}
    
    c.execute('SELECT SUM(citation_count) as total_cites FROM papers')
    total_cites = c.fetchone()['total_cites'] or 0
    
    conn.close()
    return {
        'total_papers': total,
        'q1_count': quartiles.get('Q1', 0),
        'q2_count': quartiles.get('Q2', 0),
        'q3_count': quartiles.get('Q3', 0),
        'q4_count': quartiles.get('Q4', 0),
        'total_citations': total_cites
    }
