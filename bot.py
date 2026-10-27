import os, sys, re, time, shutil, subprocess, tempfile, asyncio, logging, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

logging.basicConfig(level=logging.INFO,
format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("codebot")

TOKEN = os.environ["BOT_TOKEN"]
ALLOWED = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_IDS = {int(x) for x in ALLOWED.split(",") if x.strip().isdigit()}
RENDER_TIMEOUT = 300
MAX_FILE_SIZE = 200_000
MAX_TEXT_LEN = 4000

PORT = int(os.environ.get("PORT", 7860))

class _Health(BaseHTTPRequestHandler):
def do_GET(self):
self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
def log_message(self, *a): pass

def _run_health():
try:
# Используем PORT, который может задать Koyeb
HTTPServer(("0.0.0.0", PORT), _Health).serve_forever()
except Exception as e: log.warning(f"health: {e}")

threading.Thread(target=_run_health, daemon=True).start()

bot = Bot(token=TOKEN)
dp = Dispatcher()
render_lock = asyncio.Lock()

def allowed(uid):
return not ALLOWED_IDS or uid in ALLOWED_IDS

HELP_TEXT = (
"🎬 Code → Video Bot\n\n"
"Пришли мне код — я превращу его в MP4.\n\n"
"Способы:\n"
"1) Пришли .py-файл\n"
"2) Или вставь код текстом в тройных ```\n\n"
"Контракт кода:\n"
"DURATION = 6\n"
"FPS = 30\n"
"WIDTH, HEIGHT = 720, 1280\n"
"def render_frame(t, W, H):\n"
" return PIL.Image\n\n"
"Лимиты: файл <= 200KB, длит. <= 20 сек, рендер <= 5 мин"
)

@dp.message(Command("start", "help"))
async def cmd_start(msg: Message):
if not allowed(msg.from_user.id):
await msg.answer("Доступ ограничен."); return
await msg.answer(HELP_TEXT)

@dp.message(Command("id"))
async def cmd_id(msg: Message):
await msg.answer(f"Твой ID: {msg.from_user.id}")

@dp.message(F.document)
async def on_document(msg: Message):
if not allowed(msg.from_user.id):
await msg.answer("Доступ ограничен."); return
doc = msg.document
name = (doc.file_name or "").lower()
if not name.endswith(".py"):
await msg.answer("Нужен .py файл."); return
if doc.file_size and doc.file_size > MAX_FILE_SIZE:
await msg.answer(f"Файл больше {MAX_FILE_SIZE // 1000} КБ."); return
code_path = f"/tmp/user_{msg.from_user.id}_{int(time.time())}.py"
await bot.download(doc, destination=code_path)
await process_code(msg, code_path, doc.file_name or "file.py")

@dp.message(F.text & ~F.text.startswith("/"))
async def on_text_code(msg: Message):
if not allowed(msg.from_user.id):
await msg.answer("Доступ ограничен."); return
text = msg.text or ""
m = re.search(r"(?:python|py)?\s*\n?(.*?)\n?", text, re.DOTALL)
code = m.group(1) if m else text
if "def render_frame" not in code:
await msg.answer("В сообщении нет def render_frame(t, W, H).")
return
if len(code) > MAX_TEXT_LEN + 500:
await msg.answer("Код слишком длинный. Пришли .py-файлом.")
return
code_path = f"/tmp/user_{msg.from_user.id}_{int(time.time())}.py"
with open(code_path, "w", encoding="utf-8") as f:
f.write(code)
await process_code(msg, code_path, "pasted_code.py")

async def process_code(msg: Message, code_path: str, filename: str):
if render_lock.locked():
await msg.answer("Другой рендер уже идёт. Твой в очереди...")
async with render_lock:
status = await msg.answer("Запускаю код...")
try:
video_path = await asyncio.to_thread(render_user_code, code_path)
await status.edit_text("Отправляю видео...")
await msg.answer_video(
FSInputFile(video_path, filename="video.mp4"),
caption=f"Готово! Источник: {filename}",
)
await status.delete()
try: os.remove(video_path)
except OSError: pass
except Exception as e:
log.exception("render failed")
err = str(e).replace("`", "'")[:600]
await status.edit_text(f"Ошибка:\n{err}")
finally:
try: os.remove(code_path)
except OSError: pass

def render_user_code(code_path: str) -> str:
out_dir = tempfile.mkdtemp(prefix="frames_")
try:
env = {
"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
"HOME": "/tmp", "TMPDIR": "/tmp",
"PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
}
proc = subprocess.run(
[sys.executable, "runner.py", code_path, out_dir],
capture_output=True, text=True,
timeout=RENDER_TIMEOUT, env=env, cwd=os.getcwd(),
)
if proc.returncode != 0:
err = (proc.stderr or "no stderr").strip()[-500:]
raise RuntimeError(err or f"exit code {proc.returncode}")
last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
if not last.startswith("OK:"):
raise RuntimeError(f"Unexpected output: {last[:200]}")
, n_str, fps_str = last.split(":")
n, fps = int(n_str), int(fps_str)
pngs = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
if len(pngs) != n:
raise RuntimeError(f"Frames mismatch: {len(pngs)}/{n}")
from moviepy.editor import ImageSequenceClip
clip = ImageSequenceClip(
[os.path.join(out_dir, p) for p in pngs], fps=fps)
out_path = f"/tmp/video{int(time.time())}.mp4"
clip.write_videofile(
out_path, fps=fps, codec="libx264", audio_codec="aac",
preset="ultrafast", verbose=False, logger=None,
ffmpeg_params=["-pix_fmt", "yuv420p"],
)
clip.close()
return out_path
finally:
shutil.rmtree(out_dir, ignore_errors=True)

async def main():
log.info("Bot starting, polling...")
await dp.start_polling(bot)

if name == "main":
asyncio.run(main())
