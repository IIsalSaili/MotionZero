"""Auto-test de la reconnaissance vocale SANS micro : Windows prononce chaque mot (voix de synthèse
françaises) dans un fichier WAV, puis Vosk le reconnaît avec la grammaire fermée.

  python tools/voice_selftest.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

from vosk import KaldiRecognizer, Model, SetLogLevel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from motionzero.voice import GRAMMAR, WORDS, accepted_words  # noqa: E402

VOICES = ["Microsoft Hortense Desktop", "Microsoft Julie", "Microsoft Paul"]
PS = r"""param([string]$Jobs)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($line in [IO.File]::ReadAllLines($Jobs, [Text.Encoding]::UTF8)) {
  $parts = $line -split '\|'
  try { $s.SelectVoice($parts[0]) } catch { Write-Host "voix absente: $($parts[0])"; continue }
  $s.SetOutputToWaveFile($parts[2], $fmt); $s.Speak($parts[1]); $s.SetOutputToNull()
}
"""


def synthesize(tmp, jobs):
    ps1 = os.path.join(tmp, "tts.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as fh:
        fh.write(PS)
    jobs_file = os.path.join(tmp, "jobs.txt")
    with open(jobs_file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(jobs))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Jobs", jobs_file],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("synthese vocale impossible")


def recognize(model, path):
    rec = KaldiRecognizer(model, 16000, GRAMMAR)
    rec.SetWords(True)
    with wave.open(path, "rb") as wf:
        data = wf.readframes(wf.getnframes())
    silence = b"\x00\x00" * 8000
    t0 = time.perf_counter()
    rec.AcceptWaveform(silence + data + silence)
    res = json.loads(rec.FinalResult())
    return res, (time.perf_counter() - t0) * 1000


def main():
    SetLogLevel(-1)
    model = Model(os.path.join(ROOT, "models", "vosk-model-small-fr-0.22"))
    tmp = tempfile.mkdtemp(prefix="mz_voice_")
    jobs, expected = [], []
    for word, spoken in WORDS.items():
        for v in VOICES:
            out = os.path.join(tmp, f"{len(jobs)}.wav")
            jobs.append(f"{v}|{spoken}|{out}")
            expected.append((word, v, out))
    synthesize(tmp, jobs)

    ok = total = 0
    lat = []
    print(f"{'mot':<12}{'voix':<28}{'reconnu':<14}{'conf':>6}{'ms':>7}")
    for word, v, path in expected:
        if not os.path.exists(path):
            continue
        res, ms = recognize(model, path)
        text = res.get("text", "")
        conf = min((w["conf"] for w in res.get("result", [])), default=0.0)
        good = text == word
        ok += good
        total += 1
        lat.append(ms)
        print(f"{word:<12}{v.replace('Microsoft ', ''):<28}{text or '-':<14}{conf:6.2f}{ms:7.0f}" + ("" if good else "  <-- ERREUR"))
    # faux positifs : des phrases hors vocabulaire ne doivent rien déclencher
    print("\nPhrases hors commandes (ne doivent rien declencher) :")
    phrases = ["bonjour comment tu vas", "je regarde un film ce soir", "il fait beau aujourd'hui",
               "on se voit demain matin", "clique sur la page suivante", "tu peux coller le texte",
               "le menu du restaurant", "arrête de faire défiler", "Iris est une jolie fleur",
               "on fait une pause café", "je copie le fichier", "retourne à la page d'accueil"]
    synthesize(tmp, [f"{VOICES[0]}|{p}|{os.path.join(tmp, f'fp{i}.wav')}" for i, p in enumerate(phrases)])
    fp = 0
    for i, p in enumerate(phrases):
        res, _ = recognize(model, os.path.join(tmp, f"fp{i}.wav"))
        raw = [(w["word"], round(w["conf"], 2)) for w in res.get("result", []) if w["word"] != "[unk]"]
        kept = [w["word"] for w in accepted_words(res)]
        fp += bool(kept)
        print(f"  '{p}' -> brut {raw or 'rien'} -> accepte {kept or 'rien'}")
    print(f"\nFaux positifs apres filtrage : {fp}/{len(phrases)} phrases")
    print(f"\nReconnus : {ok}/{total}   latence moyenne : {sum(lat) / max(len(lat), 1):.0f} ms")


if __name__ == "__main__":
    main()
