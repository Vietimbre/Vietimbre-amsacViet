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
from concurrent.futures import ThreadPoolExecutor

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

def tts(region, word, path):
    req = urllib.request.Request(API, data=speak_text(word).encode("utf-8"), method="POST",
                                 headers={"api-key": KEYS[region], "api_key": KEYS[region], "voice": VOICE[region], "speed": "-1", "format": "mp3"})
    for attempt in range(4):
        try:
            res = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3: time.sleep(10 * (attempt + 1)); continue
            return f"LỖI {e.code}: {e.read()[:200]!r}"
        except Exception as e:
            if attempt < 3: time.sleep(5); continue
            return f"LỖI: {e}"
    if res.get("error") != 0 or not res.get("async"):
        return f"LỖI: {res.get('message')}"
    # File được tạo bất đồng bộ: chờ tối đa ~3 phút cho tới khi tải được
    for _ in range(60):
        time.sleep(3)
        try:
            r = urllib.request.urlopen(res["async"], timeout=30)
            data = r.read()
            if len(data) > 500:
                full = os.path.join(ROOT, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                open(full, "wb").write(data)
                return "ok"
        except urllib.error.HTTPError:
            pass
        except Exception:
            pass
    return "LỖI: chờ quá lâu, lần chạy sau sẽ thử lại"

def main():
    missing = [r for r, k in KEYS.items() if not k]
    if len(missing) == 3: sys.exit("Chưa có khóa API: hãy dán khóa vào .github/workflows/tao-am-thanh.yml")
    for r in missing: print(f"⚠ Chưa có khóa cho miền '{r}', bỏ qua miền này.")
    jobs = [j for j in load_words() if j[0] not in missing]
    if MAX_WORDS: jobs = jobs[:MAX_WORDS]
    print(f"Cần tạo {len(jobs)} file. Giọng: {VOICE}")
    ok = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for (region, word, path), result in zip(jobs, ex.map(lambda j: tts(*j), jobs)):
            ok += result == "ok"
            print(f"[{region}] {word} -> {path}: {result}")
    print(f"Xong: {ok}/{len(jobs)} file mới.")

if __name__ == "__main__":
    main()
