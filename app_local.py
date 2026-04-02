import os, random, string
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, 'media'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, 'files'), exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'grupo-as-multi-local'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ─── MODELS ───────────────────────────────────────────────────────────────────

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    product = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    link = db.Column(db.String(500))
    kit = db.Column(db.Integer, nullable=False)
    price_discount = db.Column(db.Float, nullable=False)
    price_full = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        return {'id':self.id,'platform':self.platform,'store':self.store,'product':self.product,
                'name':self.name,'link':self.link,'kit':self.kit,'price_discount':self.price_discount,
                'price_full':self.price_full,'created_at':self.created_at.isoformat(),
                'updated_at':self.updated_at.isoformat()}

class PriceTable(db.Model):
    __tablename__ = 'price_table'
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100), nullable=False)
    kit = db.Column(db.Integer, nullable=False)
    price_discount = db.Column(db.Float, default=0.0)
    price_full = db.Column(db.Float, default=0.0)
    position = db.Column(db.Integer, default=0)
    def to_dict(self):
        return {'id':self.id,'product_name':self.product_name,'kit':self.kit,
                'price_discount':self.price_discount,'price_full':self.price_full,'position':self.position}

class FiscalInfo(db.Model):
    __tablename__ = 'fiscal_info'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.String(500), default='')
    def to_dict(self):
        return {'id':self.id,'key':self.key,'value':self.value or ''}

class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(100), nullable=False)
    login = db.Column(db.String(200), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    def to_dict(self):
        return {'id':self.id,'store_name':self.store_name,'login':self.login,'password':self.password}

class FileEntry(db.Model):
    __tablename__ = 'files'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    local_path = db.Column(db.String(1000))   # path relativo dentro de uploads/
    folder_path = db.Column(db.String(500), default='/')
    file_type = db.Column(db.String(100), default='')
    is_folder = db.Column(db.Boolean, default=False)
    size = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        url = f'/uploads/{self.local_path}' if self.local_path else None
        return {'id':self.id,'name':self.name,'cloudinary_url':url,'cloudinary_id':self.local_path,
                'folder_path':self.folder_path,'file_type':self.file_type,'is_folder':self.is_folder,
                'size':self.size,'created_at':self.created_at.isoformat()}

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        return {'id':self.id,'username':self.username,'message':self.message,
                'created_at':self.created_at.isoformat()}

class MediaFile(db.Model):
    __tablename__ = 'media_files'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    local_path = db.Column(db.String(1000))
    file_type = db.Column(db.String(100), default='')
    size = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        url = f'/uploads/{self.local_path}' if self.local_path else None
        return {'id':self.id,'name':self.name,'cloudinary_url':url,'cloudinary_id':self.local_path,
                'file_type':self.file_type,'size':self.size,'uploaded_by':self.uploaded_by,
                'created_at':self.created_at.isoformat()}

# ─── SEED DATA ────────────────────────────────────────────────────────────────

PRODUCTS = ['Baby Look','Body Manga Curta','Body Gola Quadrada','Body Gola Alta',
            'Baby Tee','Blusinhas Regata','Mula Manca','Top Academia',
            'Body Regata','Top Faixa','Blusinha T-Shirt','Blusinha Costa Nua']

STORES = {'Shopee':['Grupo AS','AS03','Gp_Variedades','Rosa Moda'],'TikTok':['Grupo AS Multi'],'Shein':[]}

FISCAL_DEFAULTS = [('CEST','28.057.00'),('CFOP Mesmo Estado','5102'),('CFOP Estado Diferente','6102'),
                   ('COSN','102'),('NCM',''),('Origem',''),('Unidade de Medida','CJ (CONJUNTO)')]

ACCOUNTS_DEFAULT = [('AS03','+55 11 97846514','William2525'),('Gp_Variedades','+55 11 959522331','Ab84777597aa'),
                    ('Rosa Modas','+55 11 961512212','A28071294Bd'),('Grupo AS','+55 11 951639438','A280712a')]

def seed_db():
    if FiscalInfo.query.count() == 0:
        for k,v in FISCAL_DEFAULTS: db.session.add(FiscalInfo(key=k,value=v))
    if Account.query.count() == 0:
        for s,l,p in ACCOUNTS_DEFAULT: db.session.add(Account(store_name=s,login=l,password=p))
    if PriceTable.query.count() == 0:
        for i,prod in enumerate(PRODUCTS):
            for kit in range(1,7):
                db.session.add(PriceTable(product_name=prod,kit=kit,price_discount=0.0,price_full=0.0,position=i))
    db.session.commit()

# ─── AUTH ─────────────────────────────────────────────────────────────────────

USERS = ['Isac','Otavio','Isadora']

@app.route('/')
def index(): return render_template('index.html')

@app.route('/uploads/<path:filename>')
def serve_upload(filename): return send_from_directory(UPLOAD_DIR, filename)

@app.route('/api/login', methods=['POST'])
def login():
    u = (request.get_json() or {}).get('username','').strip()
    if u in USERS:
        session['username'] = u
        return jsonify({'success':True,'username':u})
    return jsonify({'success':False,'error':'Usuário não encontrado'}), 401

@app.route('/api/logout', methods=['POST'])
def logout(): session.pop('username',None); return jsonify({'success':True})

@app.route('/api/me')
def me():
    u = session.get('username')
    return jsonify({'logged_in':bool(u),'username':u})

# ─── ANNOUNCEMENTS ────────────────────────────────────────────────────────────

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    q = Announcement.query
    p = request.args.get('platform')
    if p and p != 'all': q = q.filter_by(platform=p)
    s = request.args.get('store')
    if s: q = q.filter_by(store=s)
    n = request.args.get('name')
    if n: q = q.filter(Announcement.name.ilike(f'%{n}%'))
    k = request.args.get('kit')
    if k: q = q.filter_by(kit=int(k))
    mn = request.args.get('min_price', type=float)
    mx = request.args.get('max_price', type=float)
    if mn is not None: q = q.filter(Announcement.price_discount >= mn)
    if mx is not None: q = q.filter(Announcement.price_discount <= mx)
    sort = request.args.get('sort','newest')
    if sort == 'newest': q = q.order_by(Announcement.created_at.desc())
    elif sort == 'updated': q = q.order_by(Announcement.updated_at.desc())
    elif sort == 'price_asc': q = q.order_by(Announcement.price_discount.asc())
    elif sort == 'price_desc': q = q.order_by(Announcement.price_discount.desc())
    elif sort == 'name_asc': q = q.order_by(Announcement.name.asc())
    return jsonify([a.to_dict() for a in q.all()])

@app.route('/api/announcements/<int:aid>', methods=['GET'])
def get_announcement(aid):
    return jsonify(Announcement.query.get_or_404(aid).to_dict())

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    d = request.get_json()
    pd = float(d.get('price_discount',0))
    a = Announcement(platform=d['platform'],store=d['store'],product=d['product'],
                     name=d['name'],link=d.get('link',''),kit=int(d['kit']),
                     price_discount=pd,price_full=pd*2)
    db.session.add(a); db.session.commit()
    socketio.emit('new_announcement', a.to_dict(), room='dashboard')
    return jsonify(a.to_dict()), 201

@app.route('/api/announcements/<int:aid>', methods=['PUT'])
def update_announcement(aid):
    a = Announcement.query.get_or_404(aid)
    d = request.get_json()
    pd = float(d.get('price_discount', a.price_discount))
    a.platform=d.get('platform',a.platform); a.store=d.get('store',a.store)
    a.product=d.get('product',a.product); a.name=d.get('name',a.name)
    a.link=d.get('link',a.link); a.kit=int(d.get('kit',a.kit))
    a.price_discount=pd; a.price_full=pd*2; a.updated_at=datetime.utcnow()
    db.session.commit()
    return jsonify(a.to_dict())

@app.route('/api/announcements/<int:aid>', methods=['DELETE'])
def delete_announcement(aid):
    a = Announcement.query.get_or_404(aid)
    db.session.delete(a); db.session.commit()
    return jsonify({'success':True})

@app.route('/api/recent_activity')
def recent_activity():
    today = datetime.utcnow().date()
    items = Announcement.query.filter(
        db.func.date(Announcement.created_at) == today
    ).order_by(Announcement.created_at.desc()).limit(20).all()
    return jsonify([a.to_dict() for a in items])

# ─── PRICES ───────────────────────────────────────────────────────────────────

@app.route('/api/prices')
def get_prices():
    return jsonify([p.to_dict() for p in PriceTable.query.order_by(PriceTable.position,PriceTable.product_name,PriceTable.kit).all()])

@app.route('/api/prices/lookup')
def price_lookup():
    p = PriceTable.query.filter_by(product_name=request.args.get('product',''),
                                    kit=request.args.get('kit',type=int)).first()
    return jsonify({'price_discount':p.price_discount,'price_full':p.price_full} if p else {'price_discount':0.0,'price_full':0.0})

@app.route('/api/prices/<int:pid>', methods=['PUT'])
def update_price(pid):
    p = PriceTable.query.get_or_404(pid)
    d = request.get_json()
    if 'price_discount' in d: p.price_discount=float(d['price_discount']); p.price_full=p.price_discount*2
    elif 'price_full' in d: p.price_full=float(d['price_full']); p.price_discount=p.price_full/2
    db.session.commit(); return jsonify(p.to_dict())

@app.route('/api/prices/product', methods=['POST'])
def add_product():
    d = request.get_json()
    pos = db.session.query(db.func.max(PriceTable.position)).scalar() or 0
    for kit in d.get('kits',[1]):
        db.session.add(PriceTable(product_name=d['product_name'],kit=kit,price_discount=0.0,price_full=0.0,position=pos+1))
    db.session.commit(); return jsonify({'success':True})

@app.route('/api/prices/product/<string:name>', methods=['PUT'])
def rename_product(name):
    d = request.get_json()
    PriceTable.query.filter_by(product_name=name).update({'product_name':d['product_name']})
    db.session.commit(); return jsonify({'success':True})

@app.route('/api/prices/product/<string:name>', methods=['DELETE'])
def delete_product(name):
    PriceTable.query.filter_by(product_name=name).delete()
    db.session.commit(); return jsonify({'success':True})

@app.route('/api/prices/reorder', methods=['POST'])
def reorder_products():
    for item in request.get_json():
        PriceTable.query.filter_by(product_name=item['product_name']).update({'position':item['position']})
    db.session.commit(); return jsonify({'success':True})

# ─── FISCAL ───────────────────────────────────────────────────────────────────

@app.route('/api/fiscal', methods=['GET'])
def get_fiscal(): return jsonify([f.to_dict() for f in FiscalInfo.query.all()])

@app.route('/api/fiscal', methods=['PUT'])
def update_fiscal():
    for item in request.get_json():
        f = FiscalInfo.query.get(item.get('id')) if item.get('id') else None
        if not f: f = FiscalInfo.query.filter_by(key=item.get('key','')).first()
        if f: f.key=(item.get('key') or f.key).strip(); f.value=item.get('value') or ''
    db.session.commit(); return jsonify({'success':True})

@app.route('/api/fiscal', methods=['POST'])
def add_fiscal():
    d = request.get_json(); key = d.get('key','').strip()
    if not key: return jsonify({'error':'key required'}), 400
    if FiscalInfo.query.filter_by(key=key).first(): return jsonify({'error':'key exists'}), 409
    f = FiscalInfo(key=key, value=d.get('value',''))
    db.session.add(f); db.session.commit()
    return jsonify(f.to_dict()), 201

@app.route('/api/fiscal/<int:fid>', methods=['DELETE'])
def delete_fiscal(fid):
    f = FiscalInfo.query.get_or_404(fid)
    db.session.delete(f); db.session.commit(); return jsonify({'success':True})

# ─── ACCOUNTS ─────────────────────────────────────────────────────────────────

@app.route('/api/accounts', methods=['GET'])
def get_accounts(): return jsonify([a.to_dict() for a in Account.query.all()])

@app.route('/api/accounts', methods=['POST'])
def add_account():
    d = request.get_json()
    a = Account(store_name=d['store_name'],login=d['login'],password=d['password'])
    db.session.add(a); db.session.commit(); return jsonify(a.to_dict()), 201

@app.route('/api/accounts/<int:aid>', methods=['PUT'])
def update_account(aid):
    a = Account.query.get_or_404(aid); d = request.get_json()
    a.store_name=d.get('store_name',a.store_name); a.login=d.get('login',a.login); a.password=d.get('password',a.password)
    db.session.commit(); return jsonify(a.to_dict())

@app.route('/api/accounts/<int:aid>', methods=['DELETE'])
def delete_account(aid):
    a = Account.query.get_or_404(aid); db.session.delete(a); db.session.commit(); return jsonify({'success':True})

# ─── MEDIA (salva localmente) ──────────────────────────────────────────────────

@app.route('/api/media', methods=['GET'])
def get_media(): return jsonify([m.to_dict() for m in MediaFile.query.order_by(MediaFile.created_at.desc()).all()])

@app.route('/api/media/upload', methods=['POST'])
def upload_media():
    file = request.files.get('file')
    if not file: return jsonify({'error':'no file'}), 400
    safe = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    rel = f'media/{safe}'
    file.save(os.path.join(UPLOAD_DIR, 'media', safe))
    m = MediaFile(name=file.filename, local_path=rel, file_type=file.content_type,
                  size=os.path.getsize(os.path.join(UPLOAD_DIR,'media',safe)),
                  uploaded_by=session.get('username',''))
    db.session.add(m); db.session.commit()
    socketio.emit('media_update',{'action':'add','file':m.to_dict()},room='media')
    return jsonify(m.to_dict()), 201

@app.route('/api/media/<int:mid>', methods=['DELETE'])
def delete_media(mid):
    m = MediaFile.query.get_or_404(mid)
    try:
        path = os.path.join(UPLOAD_DIR, m.local_path)
        if os.path.exists(path): os.remove(path)
    except: pass
    db.session.delete(m); db.session.commit()
    socketio.emit('media_update',{'action':'delete','id':mid},room='media')
    return jsonify({'success':True})

# ─── FILES (salva localmente) ──────────────────────────────────────────────────

@app.route('/api/files', methods=['GET'])
def get_files():
    folder = request.args.get('folder','/')
    items = FileEntry.query.filter_by(folder_path=folder).order_by(FileEntry.is_folder.desc(),FileEntry.name).all()
    return jsonify([f.to_dict() for f in items])

@app.route('/api/files/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file'); folder = request.form.get('folder','/')
    if not file: return jsonify({'error':'no file'}), 400
    sub = folder.lstrip('/')
    dest_dir = os.path.join(UPLOAD_DIR,'files',sub)
    os.makedirs(dest_dir, exist_ok=True)
    safe = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    full = os.path.join(dest_dir, safe)
    file.save(full)
    rel = f"files/{sub}/{safe}".replace('//','/')
    f = FileEntry(name=file.filename, local_path=rel, folder_path=folder,
                  file_type=file.content_type, is_folder=False,
                  size=os.path.getsize(full))
    db.session.add(f); db.session.commit()
    socketio.emit('files_update',{'action':'add','file':f.to_dict()},room='files')
    return jsonify(f.to_dict()), 201

@app.route('/api/files/folder', methods=['POST'])
def create_folder():
    d = request.get_json()
    f = FileEntry(name=d['name'], folder_path=d.get('parent','/'), is_folder=True)
    db.session.add(f); db.session.commit()
    socketio.emit('files_update',{'action':'add','file':f.to_dict()},room='files')
    return jsonify(f.to_dict()), 201

@app.route('/api/files/<int:fid>', methods=['DELETE'])
def delete_file(fid):
    f = FileEntry.query.get_or_404(fid)
    if not f.is_folder and f.local_path:
        try:
            p = os.path.join(UPLOAD_DIR, f.local_path)
            if os.path.exists(p): os.remove(p)
        except: pass
    db.session.delete(f); db.session.commit()
    socketio.emit('files_update',{'action':'delete','id':fid},room='files')
    return jsonify({'success':True})

# ─── STORES / PRODUCTS ────────────────────────────────────────────────────────

@app.route('/api/stores')
def get_stores(): return jsonify(STORES)

@app.route('/api/products')
def get_products(): return jsonify(PRODUCTS)

# ─── CHAT HTTP ────────────────────────────────────────────────────────────────

@app.route('/api/chat/history')
def chat_history_http():
    msgs = ChatMessage.query.order_by(ChatMessage.created_at.asc()).all()
    return jsonify([m.to_dict() for m in msgs])

# ─── SOCKET.IO ────────────────────────────────────────────────────────────────

ttt_queue = []
ttt_games = {}

@socketio.on('connect')
def on_connect():
    u = session.get('username')
    if u: emit('connected',{'username':u})

@socketio.on('join_room')
def on_join(d): join_room(d.get('room'))

@socketio.on('leave_room')
def on_leave(d): leave_room(d.get('room'))

@socketio.on('chat_message')
def handle_chat(data):
    u = session.get('username','Desconhecido')
    msg = (data.get('message') or '').strip()
    if not msg: return
    m = ChatMessage(username=u, message=msg)
    db.session.add(m); db.session.commit()
    emit('chat_message',{'id':m.id,'username':u,'message':msg,'created_at':m.created_at.isoformat()},room='chat')

@socketio.on('ttt_join_queue')
def ttt_join_queue():
    u = session.get('username','?'); sid = request.sid
    if any(p['sid']==sid for p in ttt_queue): return
    ttt_queue.append({'sid':sid,'username':u})
    if len(ttt_queue) >= 2:
        p1,p2 = ttt_queue.pop(0), ttt_queue.pop(0)
        gid = ''.join(random.choices(string.ascii_lowercase,k=8))
        ttt_games[gid] = {'board':['']*9,'players':{'X':p1,'O':p2},'current':'X','winner':None}
        socketio.emit('ttt_start',{'game_id':gid,'symbol':'X','opponent':p2['username']},room=p1['sid'])
        socketio.emit('ttt_start',{'game_id':gid,'symbol':'O','opponent':p1['username']},room=p2['sid'])
    else:
        emit('ttt_waiting',{})

@socketio.on('ttt_move')
def ttt_move(data):
    g = ttt_games.get(data.get('game_id'))
    if not g or g['winner']: return
    idx, sym = data.get('index'), data.get('symbol')
    if g['board'][idx] or g['current'] != sym: return
    g['board'][idx] = sym
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    winner = next((g['board'][a] for a,b,c in wins if g['board'][a] and g['board'][a]==g['board'][b]==g['board'][c]),None)
    if not winner and all(g['board']): winner = 'draw'
    g['winner'] = winner; g['current'] = 'O' if sym=='X' else 'X'
    for pl in g['players'].values():
        socketio.emit('ttt_update',{'board':g['board'],'current':g['current'],'winner':winner},room=pl['sid'])
    if winner: del ttt_games[data['game_id']]

@socketio.on('ttt_leave_queue')
def ttt_leave_queue():
    global ttt_queue; ttt_queue = [p for p in ttt_queue if p['sid'] != request.sid]

# ─── SCHEDULER: limpa chat a cada 5 min ───────────────────────────────────────

def clear_chat():
    with app.app_context():
        ChatMessage.query.delete(); db.session.commit()
        socketio.emit('chat_cleared',{},room='chat')

scheduler = BackgroundScheduler()
scheduler.add_job(clear_chat,'interval',minutes=5)
scheduler.start()

# ─── STARTUP ──────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_db()

if __name__ == '__main__':
    print('\n🚀 Sistema rodando em http://localhost:5000')
    print('   Na rede local: http://<seu-ip>:5000\n')
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
