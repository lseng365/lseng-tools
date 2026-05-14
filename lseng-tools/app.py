import os
import uuid
import fitz
import ezdxf
from flask import Flask, request, send_file, jsonify, render_template
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

UPLOAD_FOLDER = '/tmp/lseng_tools'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MM_PER_PT = 25.4 / 72.0

# ──────────────────────────────────────────
# 홈 화면
# ──────────────────────────────────────────
@app.route('/')
def index():
    tools = [
        {
            'id': 'pdf-to-dxf',
            'name': 'PDF → DXF 변환',
            'desc': 'CAD 도면 PDF를 AutoCAD용 DXF 파일로 변환',
            'icon': '📐',
            'url': '/pdf-to-dxf',
            'badge': 'NEW',
        },
        # 향후 도구 추가 시 여기에 딕셔너리 추가
    ]
    return render_template('index.html', tools=tools)


# ──────────────────────────────────────────
# PDF → DXF 도구
# ──────────────────────────────────────────
@app.route('/pdf-to-dxf')
def pdf_to_dxf_page():
    return render_template('pdf_to_dxf.html')


@app.route('/api/pdf-to-dxf', methods=['POST'])
def pdf_to_dxf_convert():
    if 'file' not in request.files:
        return jsonify(error='파일이 없습니다.'), 400

    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify(error='PDF 파일만 업로드 가능합니다.'), 400

    uid = str(uuid.uuid4())[:8]
    orig_name = os.path.splitext(secure_filename(f.filename))[0]
    pdf_path = os.path.join(UPLOAD_FOLDER, f'{uid}.pdf')
    dxf_path = os.path.join(UPLOAD_FOLDER, f'{uid}.dxf')
    f.save(pdf_path)

    try:
        doc_pdf = fitz.open(pdf_path)
        page = doc_pdf[0]
        drawings = page.get_drawings()

        if len(drawings) < 50:
            return jsonify(error='벡터 데이터가 없는 래스터 PDF입니다. 현재 벡터 PDF만 지원합니다.'), 400

        doc_dxf = ezdxf.new(dxfversion='R2010')
        doc_dxf.units = 4
        msp = doc_dxf.modelspace()
        _convert_vector(page, msp, doc_dxf)
        doc_dxf.saveas(dxf_path)

    except Exception as e:
        return jsonify(error=f'변환 오류: {str(e)}'), 500
    finally:
        try:
            os.remove(pdf_path)
        except:
            pass

    return send_file(dxf_path, as_attachment=True,
                     download_name=f'{orig_name}.dxf',
                     mimetype='application/dxf')


def _convert_vector(page, msp, doc_dxf):
    page_h = page.rect.height
    page_w = page.rect.width

    for name, color in [("LINES",7),("CURVES",3),("RECTANGLES",5),("RED_LINES",1),("TEXT",2)]:
        doc_dxf.layers.add(name, color=color)

    def pt(x, y):
        return x * MM_PER_PT, (page_h - y) * MM_PER_PT

    for drw in page.get_drawings():
        sc, fc = drw.get('color'), drw.get('fill')
        rect = drw.get('rect')
        if rect and rect.width > page_w * 0.3 and fc is not None:
            continue
        layer = "RED_LINES" if (sc and len(sc)==3 and sc[0]>0.5 and sc[1]<0.3 and sc[2]<0.3) else "LINES"

        for item in drw.get('items', []):
            t = item[0]
            if t == 'l':
                msp.add_line(pt(item[1].x,item[1].y), pt(item[2].x,item[2].y), dxfattribs={"layer":layer})
            elif t == 're':
                r = item[1]
                x1,y1=pt(r.x0,r.y0); x2,y2=pt(r.x1,r.y1)
                msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)],
                                   dxfattribs={"layer":"RECTANGLES","closed":True})
            elif t == 'c':
                p0,p1,p2,p3 = item[1],item[2],item[3],item[4]
                pts = []
                for i in range(17):
                    tt=i/16; s=1-tt
                    bx=s**3*p0.x+3*s**2*tt*p1.x+3*s*tt**2*p2.x+tt**3*p3.x
                    by=s**3*p0.y+3*s**2*tt*p1.y+3*s*tt**2*p2.y+tt**3*p3.y
                    pts.append(pt(bx,by))
                for i in range(len(pts)-1):
                    msp.add_line(pts[i], pts[i+1], dxfattribs={"layer":"CURVES"})
            elif t == 'qu':
                q = item[1]
                msp.add_lwpolyline(
                    [pt(q.ul.x,q.ul.y),pt(q.ur.x,q.ur.y),pt(q.lr.x,q.lr.y),pt(q.ll.x,q.ll.y)],
                    dxfattribs={"layer":layer,"closed":True})

    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0: continue
        for line in block.get("lines",[]):
            for span in line.get("spans",[]):
                txt = span.get("text","").strip()
                if not txt: continue
                ox,oy = span["origin"]
                try:
                    msp.add_text(txt, dxfattribs={
                        "layer":"TEXT",
                        "height": max(span.get("size",8)*MM_PER_PT, 1.5),
                        "insert": pt(ox,oy)
                    })
                except: pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
