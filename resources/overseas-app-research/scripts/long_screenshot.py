"""Stitch original screen pixels with unique exact vertical overlap; verify provenance."""
import argparse
import datetime
import hashlib
import json
from math import ceil
from pathlib import Path
import sys
import uuid


class StitchError(ValueError):
    pass


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_images(paths):
    from PIL import Image

    images = []
    for path in paths:
        with Image.open(path) as source:
            if source.format != "PNG":
                raise StitchError("NOT_PNG: 原帧必须是无损 PNG")
            images.append(source.convert("RGB"))
    return images


def row_hashes(image, left, top, right, bottom):
    data = image.crop((left, top, right, bottom)).tobytes()
    stride = (right - left) * 3
    return [hashlib.sha256(data[i:i + stride]).digest() for i in range(0, len(data), stride)]


def plan(images, config):
    if len(images) < 2:
        raise StitchError("TOO_FEW_FRAMES: 长图至少需要两张发生滚动的原帧；单屏直接保留原图")
    width, height = images[0].size
    if any(image.size != (width, height) for image in images):
        raise StitchError("SIZE_CHANGED: 原帧尺寸不同；检查旋转、分辨率或宿主变化后重新采集")
    top, bottom = config["top"], config["bottom"]
    left, right = config["match_left"], config["match_right"]
    minimum = config["min_overlap"]
    if not (0 <= top < bottom <= height and 0 <= left < right <= width
            and 1 <= minimum < bottom - top):
        raise StitchError("INVALID_REGION: 检查滚动内容边界、匹配横向范围和最小重叠行数")
    required_overlap = ceil((bottom - top) * 0.3)
    if minimum < required_overlap:
        raise StitchError(f"INSUFFICIENT_OVERLAP_REQUIREMENT: 最小重叠须至少为内容区高度的 30%（{required_overlap} 行），不能降低至 {minimum} 行")
    rows = [row_hashes(im, left, top, right, bottom) for im in images]
    content_height = bottom - top
    segments = [{"source_index": 0, "start_y": 0, "end_y": bottom, "output_y": 0}]
    transitions = []
    output_y = bottom
    for index in range(1, len(images)):
        previous, current = rows[index - 1], rows[index]
        pair = f"帧 {index - 1} → {index}"
        if previous == current:
            raise StitchError(f"NO_SCROLL_MOVEMENT: {pair} 内容相同；可能到底、手势无效或重复内容，不能自动认定到底")
        candidates = [shift for shift in range(1, content_height - minimum + 1)
                      if previous[shift:] == current[:content_height - shift]]
        if not candidates:
            raise StitchError(f"NO_EXACT_OVERLAP: {pair} 无可靠重叠；检查滚动过大、动态内容、固定栏、滚动条或状态变化，补拍")
        if len(candidates) != 1:
            raise StitchError(f"AMBIGUOUS_OVERLAP: {pair} 有多个匹配位移 {candidates[:8]}；重复/空白内容无法唯一定位，补充可定位原帧")
        shift = candidates[0]
        transitions.append({"previous_index": index - 1, "next_index": index,
                            "shift": shift, "overlap_rows": content_height - shift,
                            "matching_pixel_error": 0})
        segments.append({"source_index": index, "start_y": bottom - shift,
                         "end_y": bottom, "output_y": output_y})
        output_y += shift
    if bottom < height:
        segments.append({"source_index": len(images) - 1, "start_y": bottom,
                         "end_y": height, "output_y": output_y})
        output_y += height - bottom
    return segments, transitions, (width, output_y)


def verify_pixels(manifest_path):
    from PIL import Image

    manifest_path = Path(manifest_path).resolve()
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if record["status"] != "stitched":
        raise StitchError("NOT_STITCHED: 该记录不是成功拼接结果")
    sources = record["frames"]
    for source in sources:
        if sha256(source["path"]) != source["sha256"]:
            raise StitchError(f"SOURCE_HASH_CHANGED: 原帧已变化 {source['path']}")
    images = load_images([source["path"] for source in sources])
    segments, transitions, size = plan(images, record["config"])
    if segments != record["segments"] or transitions != record["transitions"]:
        raise StitchError("PLAN_CHANGED: 原帧匹配与记录中的位移/裁切不一致")
    output = manifest_path.parent / record["output"]["file"]
    if sha256(output) != record["output"]["sha256"]:
        raise StitchError("OUTPUT_HASH_CHANGED: 长图文件哈希不一致")
    with Image.open(output) as saved:
        saved = saved.convert("RGB")
        if saved.size != size or list(size) != record["output"]["size"]:
            raise StitchError("OUTPUT_SIZE_CHANGED: 长图尺寸不一致")
        for segment in segments:
            start, end, y = segment["start_y"], segment["end_y"], segment["output_y"]
            actual = saved.crop((0, y, size[0], y + end - start)).tobytes()
            original = images[segment["source_index"]].crop((0, start, size[0], end)).tobytes()
            if actual != original:
                raise StitchError("PIXELS_CHANGED: 长图像素与所记录原帧裁切不同")
    return {"status": "passed", "source_pixels_unchanged": True,
            "coverage": "requires_top_bottom_and_container_review",
            "manifest": str(manifest_path)}


def verify(manifest_path):
    """Persist every check, including failures; the latest report never stays stale."""
    manifest_path = Path(manifest_path).resolve()
    result = {"status": "failed", "manifest": str(manifest_path),
              "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "coverage": "requires_top_bottom_and_container_review",
              "manifest_sha256": None, "observed_output_sha256": None, "observed_sources": []}
    try:
        result["manifest_sha256"] = sha256(manifest_path)
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        for source in record["frames"]:
            path = Path(source["path"])
            result["observed_sources"].append({"path": str(path), "sha256": sha256(path) if path.is_file() else None})
        if "output" in record:
            output = manifest_path.parent / record["output"]["file"]
            result["observed_output_sha256"] = sha256(output) if output.is_file() else None
        result.update(verify_pixels(manifest_path))
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        history = manifest_path.parent / "verification-history"
        history.mkdir(exist_ok=True)
        write_json(history / (uuid.uuid4().hex + ".json"), result)
        write_json(manifest_path.parent / "verification.json", result)
    return result


def stitch(paths, out, config):
    from PIL import Image

    out = Path(out).resolve()
    # A fresh attempt directory prevents overwriting frames or previous results.
    out.mkdir(parents=True, exist_ok=False)
    record = {"status": "failed", "frames": [{"path": str(Path(p).resolve())} for p in paths],
              "config": config, "coverage": "requires_top_bottom_and_container_review"}
    manifest = out / "stitch.json"
    try:
        for source in record["frames"]:
            source["sha256"] = sha256(source["path"])
        images = load_images([source["path"] for source in record["frames"]])
        segments, transitions, size = plan(images, config)
        joined = Image.new("RGB", size)
        for segment in segments:
            crop = images[segment["source_index"]].crop(
                (0, segment["start_y"], size[0], segment["end_y"]))
            joined.paste(crop, (0, segment["output_y"]))
        output = out / "long.png"
        joined.save(output)
        record.update(status="stitched", segments=segments, transitions=transitions,
                      output={"file": output.name, "size": list(size), "sha256": sha256(output)})
        write_json(manifest, record)
        verify(manifest)
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(manifest, record)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("stitch", help="拼接按从上到下顺序排列的 PNG 原帧")
    capture.add_argument("--frames", nargs="+", required=True)
    capture.add_argument("--top", type=int, required=True, help="滚动内容区起始行（含）")
    capture.add_argument("--bottom", type=int, required=True, help="滚动内容区结束行（不含）")
    capture.add_argument("--match-left", type=int, required=True)
    capture.add_argument("--match-right", type=int, required=True, help="匹配区右边界（不含）；只影响匹配，不裁掉输出像素")
    capture.add_argument("--min-overlap", type=int, required=True, help="至少保留的重叠行数，不低于内容区高度的 30%（向上取整）")
    capture.add_argument("--out", required=True, help="尚不存在的本次拼接目录")
    check = commands.add_parser("verify", help="重新核对原帧/长图哈希、匹配位移和全部来源像素")
    check.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        if args.command == "stitch":
            config = {key: getattr(args, key) for key in
                      ("top", "bottom", "match_left", "match_right", "min_overlap")}
            result = {"manifest": str(stitch(args.frames, args.out, config)), "status": "stitched"}
        else:
            result = verify(args.manifest)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, ImportError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
