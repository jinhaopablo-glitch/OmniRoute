"""Montaje de vídeos verticales (1080x1920) con FFmpeg.

Cada escena usa una imagen (de producto o propia) con un zoom suave, o una
tarjeta con el color de marca si no hay imagen. Se añaden subtítulos
quemados con estilo PUAVI y, si existe, la voz en off.

FFmpeg se invoca con una lista de argumentos (sin shell), así que el texto de
los guiones nunca se interpreta como comandos.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 30

# Colores PUAVI en formato ASS (&HAABBGGRR).
_GREEN = "&H002B3D20"
_CREAM = "&H00D8EBF5"
_FFMPEG_TIMEOUT = 600


class VideoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scene:
    seconds: float
    text: str  # texto en pantalla / subtítulo
    image: Path | None = None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(args: list[str]) -> None:
    proc = subprocess.run(  # noqa: S603 - argumentos fijos, sin shell
        args, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT, check=False
    )
    if proc.returncode != 0:
        raise VideoError(f"FFmpeg falló: {proc.stderr[-800:]}")


def media_duration(path: Path) -> float:
    proc = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise VideoError(f"ffprobe falló: {proc.stderr[-300:]}")
    return float(json.loads(proc.stdout)["format"]["duration"])


def _ass_time(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N").strip()


def build_ass(scenes: list[Scene], durations: list[float], font: str = "DejaVu Sans") -> str:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}",
        f"PlayResY: {HEIGHT}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Puavi,{font},64,{_CREAM},{_CREAM},{_GREEN},{_GREEN},-1,0,0,0,100,100,0,0,"
        "3,18,0,2,80,80,260,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t = 0.0
    for scene, d in zip(scenes, durations, strict=True):
        if scene.text.strip():
            lines.append(
                f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + d)},Puavi,,0,0,0,,"
                f"{_ass_escape(scene.text)}"
            )
        t += d
    return "\n".join(lines) + "\n"


def scene_durations(scenes: list[Scene], audio_seconds: float | None) -> list[float]:
    base = [max(1.5, min(s.seconds, 15.0)) for s in scenes]
    if not audio_seconds:
        return base
    total = sum(base)
    factor = (audio_seconds + 0.5) / total
    return [round(d * factor, 2) for d in base]


def render_vertical_video(
    scenes: list[Scene],
    out_path: Path,
    *,
    voiceover: Path | None = None,
    max_seconds: float = 90.0,
) -> float:
    """Renderiza el vídeo y devuelve su duración en segundos."""
    if not scenes:
        raise VideoError("El guion no tiene escenas")
    if not ffmpeg_available():
        raise VideoError("FFmpeg no está instalado")
    audio_s = media_duration(voiceover) if voiceover else None
    durations = scene_durations(scenes, audio_s)
    if sum(durations) > max_seconds:
        raise VideoError(f"El vídeo supera {max_seconds:.0f} s")

    with tempfile.TemporaryDirectory(prefix="puavi-video-") as tmp_dir:
        tmp = Path(tmp_dir)
        clips: list[Path] = []
        for i, (scene, d) in enumerate(zip(scenes, durations, strict=True)):
            clip = tmp / f"clip{i:02d}.mp4"
            frames = int(d * FPS)
            if scene.image and scene.image.exists():
                vf = (
                    f"scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,"
                    f"crop={WIDTH * 2}:{HEIGHT * 2},"
                    f"zoompan=z='min(zoom+0.0008,1.12)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
                    "format=yuv420p"
                )
                _run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loop",
                        "1",
                        "-i",
                        str(scene.image),
                        "-vf",
                        vf,
                        "-t",
                        f"{d:.2f}",
                        "-r",
                        str(FPS),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-an",
                        str(clip),
                    ]
                )
            else:
                _run(
                    [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c=0x203D2B:s={WIDTH}x{HEIGHT}:r={FPS}:d={d:.2f}",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-pix_fmt",
                        "yuv420p",
                        str(clip),
                    ]
                )
            clips.append(clip)

        concat_list = tmp / "list.txt"
        concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        joined = tmp / "joined.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(joined),
            ]
        )

        ass = tmp / "subs.ass"
        ass.write_text(build_ass(scenes, durations), encoding="utf-8")
        args = ["ffmpeg", "-y", "-i", str(joined)]
        if voiceover:
            args += ["-i", str(voiceover)]
        # La ruta del .ass se pasa por nombre relativo desde el directorio temporal.
        args += [
            "-vf",
            "subtitles=subs.ass",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
        if voiceover:
            args += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        out_tmp = tmp / "final.mp4"
        args.append(str(out_tmp))
        proc = subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT, check=False, cwd=tmp
        )
        if proc.returncode != 0:
            raise VideoError(f"FFmpeg falló al añadir subtítulos: {proc.stderr[-800:]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out_tmp), out_path)
    return media_duration(out_path)
