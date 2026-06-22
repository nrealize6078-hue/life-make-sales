"""ローカル文字起こし(faster-whisper)。whisper_venv(Python3.9)で実行する単体スクリプト。
使い方: whisper_venv/python.exe whisper_local.py <audio_path> [model]
結果は最終行に JSON で出力: {"text": "...", "language": "ja"}
"""
import sys
import json


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"text": "", "error": "no audio path"}, ensure_ascii=False))
        return
    audio = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "small"

    from faster_whisper import WhisperModel

    # CPU + int8 で軽量・高速。モデルは初回のみ自動ダウンロード(以後キャッシュ)。
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio, language="ja", beam_size=1, vad_filter=True)
    text = "".join(seg.text for seg in segments).strip()
    print(json.dumps({"text": text, "language": getattr(info, "language", "ja")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
