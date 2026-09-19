# -*- coding: utf-8 -*-
"""core 层：配置 / 连接池 / 安全 / 日志 / 指标（工业级壳层 v2）"""
import os, sys, io, json, time, secrets, hashlib, logging, threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, 'buffer') and not getattr(sys.stdout, '_flood_wrapped', False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stdout._flood_wrapped = True

# ---------------- 配置（.env 优先，环境变量次之，默认值兜底） ----------------
class Settings:
    def __init__(self):
        env = {}
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        if os.path.exists(p):
            for line in open(p, encoding='utf-8'):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
        g = env.get
        self.DB_HOST = os.environ.get('DB_HOST') or g('DB_HOST', 'localhost')
        self.DB_PORT = int(os.environ.get('DB_PORT') or g('DB_PORT', '5432'))
        self.DB_USER = os.environ.get('DB_USER') or g('DB_USER', 'postgres')
        self.DB_PASSWORD = os.environ.get('DB_PASSWORD') or g('DB_PASSWORD', '123456')
        self.DB_NAME = os.environ.get('DB_NAME') or g('DB_NAME', 'gis_flood')
        self.APP_VERSION = '2.0.0'
        self.WALK_SPEED_MPS = 1.2
        self.TOKEN_TTL_HOURS = 72
        self.TDT_KEY = os.environ.get('TDT_KEY') or g('TDT_KEY', '')
        self.WAQI_TOKEN = os.environ.get('WAQI_TOKEN') or g('WAQI_TOKEN', '')
        # 研究区范围
        self.BBOX = (119.19, 26.03, 119.30, 26.10)
        self.AQ_BBOX = (118.55, 25.35, 120.05, 26.75)   # 福州市域（AQ 主题，匹配 CAMS 11km 分辨率）

SETTINGS = Settings()

# ---------------- 日志 ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger('flood')

# ---------------- 连接池 ----------------
import psycopg2
import psycopg2.pool
import psycopg2.extras

_pool = None
_pool_lock = threading.Lock()

def init_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=12,
                host=SETTINGS.DB_HOST, port=SETTINGS.DB_PORT,
                user=SETTINGS.DB_USER, password=SETTINGS.DB_PASSWORD,
                dbname=SETTINGS.DB_NAME)
    return _pool

@contextmanager
def get_conn():
    init_pool()
    # 池满时排队等待而非直接抛错（ThreadedConnectionPool 默认行为 = 立即 PoolError）
    conn = None
    deadline = time.time() + 10
    while conn is None:
        try:
            conn = _pool.getconn()
        except psycopg2.pool.PoolError:
            if time.time() > deadline:
                raise
            time.sleep(0.05)
    try:
        yield conn
    finally:
        _pool.putconn(conn)

def query(cur, sql, params=None, one=False):
    cur.execute(sql, params or ())
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows

# ---------------- 安全（PBKDF2 + DB 会话） ----------------
PBKDF2_ITERS = 100_000

def hash_password(pwd: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), PBKDF2_ITERS)
    return f'pbkdf2${PBKDF2_ITERS}${salt}${dk.hex()}'

def verify_password(pwd: str, stored: str) -> bool:
    try:
        algo, iters, salt, expect = stored.split('$')
        if algo != 'pbkdf2':
            return False
        dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), int(iters))
        return secrets.compare_digest(dk.hex(), expect)
    except Exception:
        return False

def create_session(cur, username: str, role: str) -> str:
    token = secrets.token_hex(24)
    exp = datetime.now(timezone.utc) + timedelta(hours=SETTINGS.TOKEN_TTL_HOURS)
    cur.execute('DELETE FROM sessions WHERE expires_at < NOW()')
    cur.execute('INSERT INTO sessions (token, username, role, expires_at) VALUES (%s,%s,%s,%s)',
                (token, username, role, exp))
    return token

def get_session(cur, token: str):
    if not token:
        return None
    row = query(cur, '''SELECT username, role FROM sessions
                        WHERE token=%s AND expires_at > NOW()''', (token,), one=True)
    return row

# ---------------- 轻量指标（文本暴露，兼容 Prometheus 抓取格式） ----------------
_metrics = {'counters': {}, 'latency_sum': 0.0, 'latency_count': 0}
_mlock = threading.Lock()

def metric_incr(name: str, v: float = 1):
    with _mlock:
        _metrics['counters'][name] = _metrics['counters'].get(name, 0) + v

def metric_latency(seconds: float):
    with _mlock:
        _metrics['latency_sum'] += seconds
        _metrics['latency_count'] += 1

def metrics_text() -> str:
    with _mlock:
        lines = ['# TYPE flood_requests_total counter',
                 'flood_process_uptime_seconds %d' % int(time.time() - START_TIME)]
        for k, v in sorted(_metrics['counters'].items()):
            lines.append(f'{k} {v}')
        if _metrics['latency_count']:
            lines.append('# TYPE flood_request_latency_avg_seconds gauge')
            lines.append('flood_request_latency_avg_seconds %.4f' %
                         (_metrics['latency_sum'] / _metrics['latency_count']))
        return '\n'.join(lines) + '\n'

START_TIME = time.time()

# ---------------- TTL 缓存（静态图层） ----------------
class TTLCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if item and time.time() < item[0]:
                return item[1]
            return None

    def put(self, key, val):
        with self._lock:
            self._d[key] = (time.time() + self.ttl, val)

    def clear(self):
        with self._lock:
            self._d.clear()
