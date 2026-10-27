import sys, os, importlib.util

def main():
    if len(sys.argv) < 3:
        print("ERROR:usage", file=sys.stderr); sys.exit(1)
    code_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    except Exception:
        pass

    try:
        spec = importlib.util.spec_from_file_location("user_module", code_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"ERROR:import:{e}", file=sys.stderr); sys.exit(2)

    if not hasattr(mod, "render_frame"):
        print("ERROR:no render_frame()", file=sys.stderr); sys.exit(3)

    duration = float(getattr(mod, "DURATION", 6))
    fps = int(getattr(mod, "FPS", 30))
    W = int(getattr(mod, "WIDTH", 720))
    H = int(getattr(mod, "HEIGHT", 1280))

    if duration <= 0 or duration > 20:
        print("ERROR:duration must be 1..20 sec", file=sys.stderr); sys.exit(4)
    if fps < 1 or fps > 60:
        print("ERROR:fps must be 1..60", file=sys.stderr); sys.exit(4)
    if W > 1080 or H > 1920 or W < 64 or H < 64:
        print("ERROR:resolution out of range", file=sys.stderr); sys.exit(4)

    n = int(duration * fps)
    from PIL import Image
    for i in range(n):
        t = i / fps
        try:
            img = mod.render_frame(t, W, H)
        except Exception as e:
            print(f"ERROR:frame {i}: {e}", file=sys.stderr); sys.exit(5)
        if not isinstance(img, Image.Image):
            print(f"ERROR:frame {i} returned {type(img).__name__}", file=sys.stderr); sys.exit(6)
        img.convert("RGB").save(os.path.join(out_dir, f"{i:05d}.png"))

    print(f"OK:{n}:{fps}")

if __name__ == "__main__":
    main()
