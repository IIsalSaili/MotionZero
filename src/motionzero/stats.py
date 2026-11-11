"""Consommation de motionzero et du PC, pour le panneau de la page d'accueil (« iris accueil »).

Mesuré une fois par seconde, et SEULEMENT quand la page est visible : réduite, rien n'est mesuré.
Chaque source (processeur, carte graphique…) peut manquer : elle vaut alors None, sans plantage.
"""
import ctypes
import logging
import os
import threading
import time
from collections import deque

log = logging.getLogger("motionzero.stats")
HISTORY = 60      # secondes gardées pour les petites courbes

# noms des fils Python -> libellé affiché (les autres fils viennent des bibliothèques : MediaPipe, Whisper, Qt…)
THREAD_LABELS = {"MainThread": "interface", "moteur": "moteur (main)", "voice": "voix (Vosk)",
                 "camera": "caméra", "whisper": "Whisper", "question": "Whisper", "type": "Whisper",
                 "ouvre": "Whisper", "ferme": "Whisper", "mesures": "ce panneau"}


class _PdhItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("status", ctypes.c_uint32), ("value", ctypes.c_double)]


class _GpuProcess:
    """Part de la carte graphique prise par CE processus (compteurs Windows : nvidia-smi dit « N/A »)."""
    PDH_FMT_DOUBLE, PDH_MORE_DATA = 0x200, 0x800007D2

    def __init__(self, pid):
        self.prefix = f"pid_{pid}_"
        self.pdh = ctypes.windll.pdh
        self.q = ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q)):
            raise OSError("PdhOpenQuery")
        self.mem = self._add(r"\GPU Process Memory(*)\Dedicated Usage")
        self.eng = self._add(r"\GPU Engine(*)\Utilization Percentage")
        self.pdh.PdhCollectQueryData(self.q)

    def _add(self, path):
        h = ctypes.c_void_p()
        if self.pdh.PdhAddEnglishCounterW(self.q, path, 0, ctypes.byref(h)):
            raise OSError("PdhAddCounter " + path)
        return h

    def _values(self, counter):
        size, count = ctypes.c_uint32(0), ctypes.c_uint32(0)
        st = self.pdh.PdhGetFormattedCounterArrayW(counter, self.PDH_FMT_DOUBLE, ctypes.byref(size),
                                                   ctypes.byref(count), None)
        if st & 0xFFFFFFFF != self.PDH_MORE_DATA:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(counter, self.PDH_FMT_DOUBLE, ctypes.byref(size),
                                                 ctypes.byref(count), buf):
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_PdhItem))
        return [(items[i].name or "", items[i].value) for i in range(count.value) if items[i].status in (0, 1)]

    def sample(self):
        """(mémoire vidéo en Mo, utilisation en %) de ce processus."""
        self.pdh.PdhCollectQueryData(self.q)
        mem = sum(v for n, v in self._values(self.mem) if n.startswith(self.prefix)) / 2**20
        # par moteur (3D, calcul, copie…) : on garde le plus chargé, comme le Gestionnaire des tâches
        per_engine = {}
        for n, v in self._values(self.eng):
            if n.startswith(self.prefix):
                kind = n.rsplit("engtype_", 1)[-1]
                per_engine[kind] = per_engine.get(kind, 0.0) + v
        return mem, min(100.0, max(per_engine.values(), default=0.0))


class Stats:
    """Une mesure par appel à sample() ; garde l'historique pour les courbes."""

    def __init__(self, info=None):
        import psutil
        self.psutil = psutil
        self.proc = psutil.Process(os.getpid())
        self.ncpu = psutil.cpu_count() or 1
        self.info = info or (lambda: {})
        self.proc.cpu_percent(None)
        psutil.cpu_percent(None, percpu=True)
        self._threads = self._thread_times()
        self._t = time.perf_counter()
        self.history = {"app_cpu": deque(maxlen=HISTORY), "pc_cpu": deque(maxlen=HISTORY),
                        "app_gpu": deque(maxlen=HISTORY), "pc_gpu": deque(maxlen=HISTORY)}
        self.nvml = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
            self.gpu_name = pynvml.nvmlDeviceGetName(self.nvml[1])
        except Exception:
            self.gpu_name = None
            log.info("carte graphique NVIDIA illisible : affichee indisponible")
        try:
            self.gpu_proc = _GpuProcess(os.getpid())
        except Exception:
            self.gpu_proc = None
            log.info("compteurs de carte graphique par processus indisponibles")

    def _thread_times(self):
        try:
            return {t.id: t.user_time + t.system_time for t in self.proc.threads()}
        except Exception:
            return {}

    def _per_thread(self, dt):
        """% d'un cœur par groupe de fils, depuis la mesure précédente."""
        now = self._thread_times()
        names = {t.native_id: t.name for t in threading.enumerate()}
        groups = {}
        for tid, cpu in now.items():
            used = cpu - self._threads.get(tid, cpu)
            label = THREAD_LABELS.get(names.get(tid, ""), None)
            if label is None:
                label = "autres fils" if tid in names else "calcul MediaPipe, Whisper, Qt"
            groups[label] = groups.get(label, 0.0) + used
        self._threads = now
        return sorted(((k, 100.0 * v / dt) for k, v in groups.items()), key=lambda kv: -kv[1])

    def sample(self):
        ps = self.psutil
        t = time.perf_counter()
        dt, self._t = max(t - self._t, 1e-3), t
        s = {"ncpu": self.ncpu}
        try:
            s["app_cpu_core"] = self.proc.cpu_percent(None)            # % d'un cœur (peut dépasser 100)
            s["app_cpu"] = s["app_cpu_core"] / self.ncpu               # % du processeur entier
            mi = self.proc.memory_info()
            s["app_ram"] = mi.rss / 2**20
            s["app_private"] = getattr(mi, "private", mi.rss) / 2**20
            s["threads"] = self._per_thread(dt)
            s["n_threads"] = self.proc.num_threads()
            prio = self.proc.nice()
            s["priority"] = {ps.BELOW_NORMAL_PRIORITY_CLASS: "inférieure à la normale",
                             ps.NORMAL_PRIORITY_CLASS: "normale", ps.IDLE_PRIORITY_CLASS: "basse",
                             ps.ABOVE_NORMAL_PRIORITY_CLASS: "supérieure", ps.HIGH_PRIORITY_CLASS: "haute"
                             }.get(prio, str(prio)) if hasattr(ps, "BELOW_NORMAL_PRIORITY_CLASS") else str(prio)
        except Exception:
            log.exception("mesure du processus impossible")
        try:
            s["cores"] = ps.cpu_percent(None, percpu=True)
            s["pc_cpu"] = sum(s["cores"]) / max(len(s["cores"]), 1)
            vm = ps.virtual_memory()
            s["pc_ram_used"], s["pc_ram_total"] = (vm.total - vm.available) / 2**30, vm.total / 2**30
        except Exception:
            log.exception("mesure du PC impossible")
        s["gpu_name"] = self.gpu_name
        if self.nvml is not None:
            try:
                nv, h = self.nvml
                s["pc_gpu"] = float(nv.nvmlDeviceGetUtilizationRates(h).gpu)
                m = nv.nvmlDeviceGetMemoryInfo(h)
                s["pc_vram_used"], s["pc_vram_total"] = m.used / 2**20, m.total / 2**20
            except Exception:
                log.exception("mesure de la carte graphique impossible")
        if self.gpu_proc is not None:
            try:
                s["app_vram"], s["app_gpu"] = self.gpu_proc.sample()
            except Exception:
                log.exception("mesure de la carte graphique (processus) impossible")
        try:
            s.update(self.info())
        except Exception:
            log.exception("etat des modeles illisible")
        for k in self.history:
            if s.get(k) is not None:
                self.history[k].append(s[k])
        s["history"] = {k: list(v) for k, v in self.history.items()}
        return s


def run_sampler(is_visible, emit, info=None, stop=None, period=1.0):
    """Fil de mesure : une mesure par seconde tant que la page est visible, rien sinon."""
    stats = None
    while stop is None or not stop.is_set():
        if is_visible():
            try:
                if stats is None:
                    stats = Stats(info)       # créé à la première ouverture seulement
                    time.sleep(0.2)           # 1re mesure de processeur : il faut un petit intervalle
                emit(stats.sample())
            except Exception:
                log.exception("panneau de consommation : mesure impossible")
        time.sleep(period)
