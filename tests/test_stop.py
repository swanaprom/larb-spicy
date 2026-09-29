"""Stopping a run (slice 5, SPEC §9 "Stopped by the operator"): during look-ups,
downloads and rendering. A stopped run ends like a failed one: nothing unverified
gets the final name, finished downloads stay cached, interrupted ones are removed."""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import (CD_MP3, CD_MP4, SEWER, THAI_MP4, XG, FakeMedia, FakeSongs,  # noqa: E402
                   PipelineTestCase, RecordingSink, row)
from larb.adapters.ffmpeg import processor  # noqa: E402
from larb.adapters.ffmpeg.helper import QUIT_GRACE_S, run_tool  # noqa: E402
from larb.core.errors import StoppedError  # noqa: E402
from larb.core.models import (ClipInfo, DownloadSettings, Level, ProcessingSettings,  # noqa: E402
                              Settings)
from larb.core.pipeline import STOPPED_MESSAGE, Pipeline  # noqa: E402
from larb.core.ports import MediaProcessor  # noqa: E402

WAIT_S = 20   # upper bound for anything a test waits for; a pass takes far less


def wait_for(condition, what):
    deadline = time.monotonic() + WAIT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.02)


class RunInThread:
    """Runs a pipeline on a worker thread, as the GUI does, and keeps its outcome."""

    def __init__(self, pipeline, countdown, settings):
        self.error = None
        self.result = None
        self.thread = threading.Thread(target=self._run, args=(pipeline, countdown, settings))
        self.thread.start()

    def _run(self, pipeline, countdown, settings):
        try:
            self.result = pipeline.run("fake-sheet", str(countdown), settings)
        except Exception as e:   # noqa: BLE001 - the test inspects whatever it was
            self.error = e

    def join(self):
        self.thread.join(WAIT_S)
        if self.thread.is_alive():
            raise AssertionError("the run didn't end after stop()")
        return self


class StopTest(PipelineTestCase):
    def pipeline(self, rows, media, sink=None, proc=None):
        return Pipeline(FakeSongs(rows), media, proc or self.processor, sink or self.sink, self.workspace)

    def output_files(self):
        folder = self.workspace / "output"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def assert_stopped(self, run):
        self.assertIsInstance(run.error, StoppedError, msg=repr(run.error))
        self.assertEqual(str(run.error), STOPPED_MESSAGE)

    def test_during_lookups(self):
        urls = [f"fx://s{n}" for n in range(6)]
        media = FakeMedia({u: (XG, 189.0) for u in urls}, lookup_delays={u: 0.3 for u in urls})
        settings = Settings(processing=ProcessingSettings(audio_only=True),
                            download=DownloadSettings(max_parallel_lookups=1))
        pipeline = self.pipeline([row(n + 2, u, "0:10-0:20") for n, u in enumerate(urls)], media)
        run = RunInThread(pipeline, CD_MP3, settings)
        wait_for(lambda: media.lookups >= 1, "the first look-up")
        pipeline.stop()
        run.join()

        self.assert_stopped(run)
        self.assertEqual(media.lookups, 1)        # the running look-up finished; the rest never started
        self.assertEqual(media.downloads, 0)
        self.assertEqual(self.output_files(), [])

    def test_during_downloads(self):
        media = FakeMedia({"fx://a": (XG, 189.0), "fx://b": (XG, 189.0), "fx://c": (SEWER, 60.0)},
                          hang_until_cancel={"fx://b"})
        settings = Settings(processing=ProcessingSettings(audio_only=True),
                            download=DownloadSettings(max_parallel_downloads=1))
        rows = [row(2, "fx://a", "0:10-0:20"), row(3, "fx://b", "0:10-0:20"), row(4, "fx://c", "0:10-0:20")]
        pipeline = self.pipeline(rows, media)
        run = RunInThread(pipeline, CD_MP3, settings)
        cache = self.workspace / "cache"
        wait_for(lambda: (cache / "b_audio.webm.part").exists(), "the interrupted download's partial file")
        pipeline.stop()
        run.join()

        self.assert_stopped(run)
        cached = sorted(p.name for p in cache.iterdir())
        self.assertEqual(cached, ["a_audio.mp3"])    # finished: kept; interrupted: removed; c: never started
        self.assertEqual(media.downloads, 1)
        self.assertEqual(self.output_files(), [])
        self.assertTrue(any("removed unfinished download b_audio.webm.part" in m
                            for m in self.sink.messages(Level.INFO)))
        # Every download that started also ended, so the GUI clears its line.
        marks = [(e.activity.key, e.activity.started) for e in self.sink.events if e.activity]
        self.assertEqual(sorted(marks), [("a_audio", False), ("a_audio", True),
                                         ("b_audio", False), ("b_audio", True)])

    def test_during_a_retry_pause(self):
        media = FakeMedia({"fx://a": (XG, 189.0)}, always_fail={"fx://a"})
        settings = Settings(processing=ProcessingSettings(audio_only=True),
                            download=DownloadSettings(max_retries=5))   # pauses of 1, 2, 3 ... s
        pipeline = self.pipeline([row(2, "fx://a", "0:10-0:20")], media)
        run = RunInThread(pipeline, CD_MP3, settings)
        wait_for(lambda: self.sink.messages(Level.WARNING), "the first retry")
        stopped_at = time.monotonic()
        pipeline.stop()
        run.join()
        self.assert_stopped(run)
        self.assertLess(time.monotonic() - stopped_at, 0.9)   # didn't sit out the pause

    def test_during_video_render(self):
        """Real FFmpeg: stopped after the first of three video chunks, while the audio
        pass is still running next to it."""
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [row(2, "fx://thai", "0:01-0:05"), row(3, "fx://thai", "0:02-0:06"),
                row(4, "fx://thai", "0:03-0:07")]
        settings = Settings(processing=ProcessingSettings(audio_only=False),
                            download=DownloadSettings(max_height=360))
        stopped_at = []

        class StopAfterFirstChunk(RecordingSink):
            def emit(self, event):
                super().emit(event)
                if event.stage == "render" and event.progress == (1, 3):
                    stopped_at.append(time.monotonic())
                    pipeline.stop()

        sink = StopAfterFirstChunk()
        proc = processor.FfmpegProcessor(self.tools, self.workspace / "tmp", sink)
        pipeline = self.pipeline(rows, media, sink, proc)
        with mock.patch.object(processor, "CHUNK_SEGMENTS", 2):      # 6 segments -> 3 chunks
            run = RunInThread(pipeline, CD_MP4, settings).join()

        self.assert_stopped(run)
        self.assertLess(time.monotonic() - stopped_at[0], QUIT_GRACE_S + 2)
        self.assertEqual(list((self.workspace / "tmp").iterdir()), [])    # chunks, audio, graphs gone
        self.assertEqual(self.output_files(), [])     # nothing was written under the output name yet
        self.assertEqual(sorted(p.name for p in (self.workspace / "cache").iterdir()), ["thai_v360.mp4"])

    def test_stopped_render_that_wrote_something_is_kept_as_failed(self):
        class StoppedMidway(MediaProcessor):
            def measure(self, path, start_s, end_s):
                return ClipInfo(60.0, peak_db=-3.0)

            def render(self, plan, output_path):
                output_path.write_bytes(b"half an output")
                raise StoppedError("Stopped")

            def describe(self):
                return "fake"

            def cancel(self):
                pass

        pipeline = self.pipeline([row(2, "fx://a", "0:10-0:20")], FakeMedia({"fx://a": (XG, 189.0)}),
                                 proc=StoppedMidway())
        with self.assertRaisesRegex(StoppedError, STOPPED_MESSAGE):
            pipeline.run("fake-sheet", str(CD_MP3), Settings(processing=ProcessingSettings(audio_only=True)))
        self.assertEqual(len(self.output_files()), 1)
        self.assertRegex(self.output_files()[0], r"^\d{4}-\d\d-\d\d_\d{6}_FAILED\.mp3$")

    def test_stop_before_the_run_starts_nothing(self):
        media = FakeMedia({"fx://a": (XG, 189.0)})
        pipeline = self.pipeline([row(2, "fx://a", "0:10-0:20")], media)
        pipeline.stop()
        with self.assertRaises(StoppedError):
            pipeline.run("fake-sheet", str(CD_MP3), Settings(processing=ProcessingSettings(audio_only=True)))
        self.assertEqual((media.lookups, media.downloads), (0, 0))


class StopFfmpegTest(PipelineTestCase):
    """The helper on its own: FFmpeg asked to quit mid-run, with no media needed."""

    def test_quits_cleanly_and_keeps_a_playable_file(self):
        out = self.workspace / "tone.mp3"
        stop = threading.Event()
        threading.Timer(1.5, stop.set).start()
        started = time.monotonic()
        with self.assertRaises(StoppedError):
            # -re: generate in real time, so this would take a minute without the stop.
            run_tool(self.tools.ffmpeg, ["-hide_banner", "-nostats", "-re", "-f", "lavfi",
                                         "-i", "sine=frequency=440:duration=60",
                                         "-c:a", "libmp3lame", str(out)], stop=stop)
        self.assertLess(time.monotonic() - started, 1.5 + QUIT_GRACE_S)   # "q" worked; not killed
        self.assertGreater(self.real_length(out), 0.5)                     # the file was closed properly

    def test_set_before_the_call_starts_nothing(self):
        stop = threading.Event()
        stop.set()
        seen = []
        with self.assertRaises(StoppedError):
            run_tool(self.tools.ffmpeg, ["-version"], on_command=seen.append, stop=stop)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
