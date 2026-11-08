#!/usr/bin/env python3
"""Say one short text through the dog's built-in voice. The text arrives on stdin.

The only route this helper can call is /speech/set_speak, so it has no path to a
head, body or navigation command. It takes the same controller lock as the other
helpers, which stops it from talking over a chess reaction or a show.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import uuid

SESSION = "/opt/vita/aorta/edu/edu_session.json5"
VERSIONS = {"aorta-sdk": "2026.9.23", "aorta-msgs": "2026.9.23", "vbot-edu-msgs": "2026.9.24", "flatbuffers": "25.12.19"}
ROUTE = "/speech/set_speak"
HUMAN_VOICE, START_PLAYING = 1, 1
MAX_CHARS = 400
CALL_TIMEOUT_MS = 30000


def emit(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


def clean(raw):
    """Models can leak reasoning or markup; none of it should be read aloud."""
    text = re.sub(r"<think>.*?(</think>|$)", " ", raw, flags=re.S | re.I)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return " ".join(text.split())[:MAX_CHARS].strip()


def speak(text, pre_check, request_id):
    os.environ["ZENOH_SESSION_CONFIG_URI"] = SESSION
    import aorta as sdk
    import set_speak_schema_meta as schema
    from aorta.services.speech.SetSpeakResponse import SetSpeakResponse

    def fill(builder, header):
        identifier = builder.CreateString(request_id)
        words = builder.CreateString(text)
        schema.SetSpeakRequestStart(builder)
        schema.SetSpeakRequestAddAortaHeader(builder, header)
        schema.SetSpeakRequestAddTargetState(builder, START_PLAYING)
        schema.SetSpeakRequestAddMode(builder, HUMAN_VOICE)
        schema.SetSpeakRequestAddReqId(builder, identifier)
        schema.SetSpeakRequestAddPreCheck(builder, pre_check)
        schema.SetSpeakRequestAddHumanLanguageText(builder, words)
        return schema.SetSpeakRequestEnd(builder)
    options = sdk.ClientOptions(timeout_ms=CALL_TIMEOUT_MS, enforce_single_provider=True, allow_retry=False)
    with sdk.Node("edu_sdk") as node:
        with node.create_client_typed(ROUTE, SetSpeakResponse.GetRootAs, request_schema_meta=schema, options=options) as client:
            response = client.call(fill).decode()
        message = response.Message()
        return response.Status(), response.ErrorCode(), (message.decode("utf-8", "replace") if isinstance(message, bytes) else message or "")[:300]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-check", action="store_true", help="Ask the speech service to validate only; makes no sound")
    args = parser.parse_args(argv)
    request_id = uuid.uuid4().hex

    def refuse(code, reason):
        emit(event="speak_refused", requestId=request_id, code=code, reason=reason)
        return 1
    text = clean(sys.stdin.read(MAX_CHARS * 8))
    if not text:
        return refuse("empty", "There is nothing to say.")
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version:
            return refuse("sdk", f"Install the documented SDK pairing: {name}=={version}")
    if not os.access(SESSION, os.R_OK):
        return refuse("sdk", "The documented EDU session file is unavailable.")
    directory = Path(__file__).resolve().parent
    with (directory / "controller.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return refuse("busy", "Another controller, such as a chess reaction or show, is using the dog.")
        if (directory / "unresolved-action.json").exists():
            return refuse("unresolved_action", "An unresolved robot action needs onsite inspection first.")
        status, error_code, message = speak(text, args.pre_check, request_id)
    spoken = status == 0 and error_code == 0
    emit(event="speak_result", requestId=request_id, ok=spoken, preCheck=args.pre_check, chars=len(text),
         status=status, errorCode=error_code, message=message)
    return 0 if spoken else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(event="error", error=type(error).__name__, message="The speech helper failed. Check the SDK setup on the dog.")
        raise SystemExit(1)
