"""Tự tạo file phát âm cho từ điển phương ngữ bằng FPT.AI Text-to-Speech.

Chạy tự động trong GitHub Actions (.github/workflows/tao-am-thanh.yml):
  - Đọc kho từ DIALECT trong index.html.
  - Từ nào CHƯA có file trong audio/tu-dien/<vùng>/ thì gọi AI đọc bằng giọng của vùng đó.
  - Từ đã có file (kể cả file người thật ghi âm) thì GIỮ NGUYÊN, không ghi đè.

Biến môi trường:
  FPT_API_KEY   khóa API lấy ở https://console.fpt.ai (lưu trong GitHub Secrets, KHÔNG dán vào code)
  VOICE_BAC, VOICE_TRUNG, VOICE_NAM   mã giọng đọc của FPT.AI cho từng miền
  MAX_WORDS     số từ tối đa mỗi lần chạy (0 = không giới hạn)
"""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.error
import socket
from concurrent.futures import ThreadPoolExecutor

# Máy chủ GitHub hay treo khi thử IPv6 ("Network is unreachable") -> chỉ dùng IPv4 cho nhanh
_getaddrinfo = socket.getaddrinfo
def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_only

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("FPT_API_URL") or "https://api.fpt.ai/hmi/tts/v5"
def _key(name):
    v = (os.environ.get(name) or "").strip()
    return "" if (not v or v.startswith("DAN_KHOA")) else v
# Mỗi miền một khóa (FPT_KEY_BAC / _TRUNG / _NAM); miền nào để trống thì dùng FPT_API_KEY chung
KEYS = {r: _key("FPT_KEY_" + r.upper()) or _key("FPT_API_KEY") for r in ("bac", "trung", "nam")}
VOICE = {
    "bac": os.environ.get("VOICE_BAC") or "banmai",
    "trung": os.environ.get("VOICE_TRUNG") or "ngoclam",
    "nam": os.environ.get("VOICE_NAM") or "linhsan",
}
MAX_WORDS = int(os.environ.get("MAX_WORDS") or 0)

# ---- Chọn dịch vụ: "viettel" (mặc định) hoặc "fpt" ----
PROVIDER = (os.environ.get("PROVIDER") or "viettel").strip().lower()
if PROVIDER == "viettel":
    API = os.environ.get("VIETTEL_API_URL") or "https://viettelai.vn/tts/speech_synthesis"
    _tok = _key("VIETTEL_TOKEN")
    KEYS = {r: _tok for r in ("bac", "trung", "nam")}
    VOICE = {
        "bac": os.environ.get("VIETTEL_VOICE_BAC") or "hn-quynhanh",
        "trung": os.environ.get("VIETTEL_VOICE_TRUNG") or "hue-maingoc",
        "nam": os.environ.get("VIETTEL_VOICE_NAM") or "hcm-thuyduyen",
    }

# ---- Tên file kiểu Telex — PHẢI giống hàm audioPath() trong index.html ----
TONE = {"̀": "f", "́": "s", "̉": "r", "̃": "x", "̣": "j"}
def telex_syl(syl):
    out, tone = "", ""
    for ch in unicodedata.normalize("NFD", syl.replace("đ", "dd").replace("Đ", "dd")).lower():
        if ch in TONE: tone = TONE[ch]
        elif ch == "̂": out += out[-1:]        # â ê ô -> aa ee oo
        elif ch in "̛̆": out += "w"       # ă ơ ư -> aw ow uw
        elif ch.isascii() and ch.isalnum(): out += ch
    return out + tone
def audio_path(region, it):
    if it.get("a"): return it["a"]
    return f"audio/tu-dien/{region}/" + "-".join(filter(None, (telex_syl(x) for x in re.split(r"[\W_]+", it["w"])))) + ".mp3"

def load_words():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    m = re.search(r"const DIALECT = (\{.*?\});\n", html)
    if not m: sys.exit("Không tìm thấy 'const DIALECT = {...};' trong index.html")
    seen, jobs = set(), []
    for region, groups in json.loads(m.group(1)).items():
        for g in groups:
            if g.get("type", "word") != "word": continue
            for it in g.get("items", []):
                if not it.get("w"): continue
                p = audio_path(region, it)
                if p in seen or os.path.exists(os.path.join(ROOT, p)): continue
                seen.add(p); jobs.append((region, it["w"], p))
    return jobs

def speak_text(word):
    t = re.sub(r"\s*/\s*", ", ", word).strip()   # "Bố / Thầy" -> "Bố, Thầy"
    return t.ljust(3, ".")                        # FPT.AI cần tối thiểu 3 ký tự

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIME_LIMIT = int(os.environ.get("TIME_LIMIT_MIN") or 40) * 60   # hết giờ thì dừng, lưu phần đã xong
WAIT_FILE = 120                                                  # chờ tối đa 2 phút cho mỗi file
START = time.time()

def log(*a): print(*a, flush=True)

def save(path, data):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(data)

def tts_viettel(region, word, path):
    body = json.dumps({"text": speak_text(word), "voice": VOICE[region], "speed": 0.9,
                       "tts_return_option": 3, "token": KEYS[region], "without_filter": False}).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "*/*",
                                          "token": KEYS[region], "User-Agent": UA})
    for attempt in range(3):
        try:
            data = urllib.request.urlopen(req, timeout=40).read()
            break
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode("utf-8", "replace")
            if e.code == 429: return "HẾT LƯỢT 429: " + msg
            if e.code in (500, 502, 503) and attempt < 2: time.sleep(10 * (attempt + 1)); continue
            return f"LỖI khi gửi {e.code}: {msg}"
        except Exception as e:
            if attempt < 2: time.sleep(5); continue
            return f"LỖI khi gửi: {e}"
    if len(data) > 300 and (data[:3] == b"ID3" or data[0] == 0xFF):
        save(path, data); return "ok"
    txt = data[:300].decode("utf-8", "replace")
    if re.search(r"quota|limit|hết|exceed|balance|ký tự", txt, re.I): return "HẾT LƯỢT: " + txt
    return f"LỖI Viettel AI trả về: {txt}"

def tts(region, word, path):
    if time.time() - START > TIME_LIMIT:
        return "bỏ qua (hết giờ, lần chạy sau làm tiếp)"
    if PROVIDER == "viettel":
        return tts_viettel(region, word, path)
    req = urllib.request.Request(API, data=speak_text(word).encode("utf-8"), method="POST",
                                 headers={"api-key": KEYS[region], "api_key": KEYS[region], "voice": VOICE[region],
                                          "speed": "-1", "format": "mp3", "User-Agent": UA})
    res = None
    for attempt in range(4):
        try:
            res = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429: return "HẾT LƯỢT 429: " + e.read()[:200].decode("utf-8", "replace")
            if e.code in (500, 502, 503) and attempt < 3: time.sleep(10 * (attempt + 1)); continue
            return f"LỖI khi gửi {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"
        except Exception as e:
            if attempt < 3: time.sleep(5); continue
            return f"LỖI khi gửi: {e}"
    if res.get("error") != 0 or not res.get("async"):
        return f"LỖI FPT.AI trả về: {json.dumps(res, ensure_ascii=False)[:300]}"
    # File được tạo bất đồng bộ: thử tải lại mỗi 3 giây
    last, t0 = "chưa có", time.time()
    while time.time() - t0 < WAIT_FILE:
        time.sleep(3)
        try:
            data = urllib.request.urlopen(urllib.request.Request(res["async"], headers={"User-Agent": UA}), timeout=30).read()
            if len(data) > 300:
                full = os.path.join(ROOT, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                open(full, "wb").write(data)
                return "ok"
            last = f"file rỗng ({len(data)} byte)"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except Exception as e:
            last = str(e)[:120]
    return f"LỖI: chờ 2 phút vẫn chưa tải được file ({last}) — {res['async']}"

DELAY = int(os.environ.get("DELAY_S") or 5)   # nghỉ giữa 2 lượt gọi để không vượt giới hạn gói miễn phí

def note(kind, title, msg):
    log(f"::{kind} title={title}::{msg}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(f"### {title}\n\n{msg}\n\n")

def main():
    missing = [r for r, k in KEYS.items() if not k]
    if len(missing) == 3: sys.exit(f"Chưa có khóa/token cho {PROVIDER}: hãy dán vào .github/workflows/tao-am-thanh.yml")
    for r in missing: log(f"⚠ Chưa có khóa cho miền '{r}', bỏ qua miền này.")
    jobs = [j for j in load_words() if j[0] not in missing]
    # xen kẽ Bắc - Trung - Nam để cả ba miền cùng có dần
    by = {r: [j for j in jobs if j[0] == r] for r in ("bac", "trung", "nam")}
    jobs = [x for grp in zip(*[by[r] + [None] * (max(map(len, by.values())) - len(by[r])) for r in by]) for x in grp if x]
    if MAX_WORDS: jobs = jobs[:MAX_WORDS]
    log(f"Dịch vụ: {PROVIDER}. Còn thiếu {len(jobs)} file. Giọng: {VOICE}. Mỗi lượt cách nhau {DELAY}s, tối đa {TIME_LIMIT // 60} phút.")
    ok, fails, out_of_quota, errs = 0, 0, set(), []
    for n, (region, word, path) in enumerate(jobs, 1):
        if region in out_of_quota: continue
        if time.time() - START > TIME_LIMIT:
            log("Hết giờ của lần chạy này, lần sau sẽ làm tiếp."); break
        t1 = time.time(); r = tts(region, word, path)
        log(f"({n}/{len(jobs)}) [{region}] {word} -> {r}  ({time.time() - t1:.0f}s)")
        if r == "ok": ok += 1
        elif r.startswith("HẾT LƯỢT"):
            out_of_quota.add(region)
            log(f"⏸ Khóa miền '{region}' đã hết lượt miễn phí, tạm dừng miền này.")
            if len(out_of_quota | set(missing)) == 3: break
            continue
        else:
            fails += 1; errs.append(f"[{region}] {word}: {r}")
            if fails >= 5 and ok == 0:
                note("error", f"{PROVIDER} báo lỗi", " | ".join(errs[:3])); sys.exit(1)
        time.sleep(DELAY)
    left = len(load_words())
    log(f"Lần này tạo được {ok} file. Còn thiếu {left} file.")
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(f"ok={ok}\nleft={left}\n")
    if out_of_quota and ok == 0:
        note("warning", f"{PROVIDER} tạm hết lượt",
             f"Các miền {sorted(out_of_quota)} đang bị giới hạn (lỗi 429). Không sao — mỗi giờ hệ thống tự thử lại, còn thiếu {left} file.")
    elif ok:
        note("notice", "Đã tạo âm thanh", f"Lần này tạo thêm {ok} file, còn thiếu {left} file.")

if __name__ == "__main__":
    main()
